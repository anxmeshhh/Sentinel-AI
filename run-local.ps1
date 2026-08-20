<#
.SYNOPSIS
  Runs Sentinel on this machine - no Docker, no venv.

.DESCRIPTION
  Four processes and two services:

    MySQL     native, already running as a Windows service (never was in Docker)
    Redis     native, already running as a Windows service
    backend   uvicorn  :8000
    worker    celery, queues: ingestion, agents
    beat      celery scheduler
    frontend  vite     :5173

  Each process opens in its own window so you can watch its log. The env is
  loaded from the single root .env - `backend/.env` used to shadow it whenever
  a command ran from backend/, which is why alembic failed on a missing
  SESSION_SECRET_KEY while Docker was fine. Its GitHub and Slack keys are
  merged into the root file now, and there is only one env file.

.EXAMPLE
  .\run-local.ps1              # preflight, migrate, start everything
  .\run-local.ps1 -Stop        # stop the four processes
  .\run-local.ps1 -NoMigrate   # skip alembic (faster restarts)
#>
param(
  [switch]$Stop,
  [switch]$NoMigrate
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Bad($msg)  { Write-Host "    $msg" -ForegroundColor Red }

# ---------------------------------------------------------------- stop --
if ($Stop) {
  Write-Step "Stopping Sentinel"
  # Ports first: whatever is serving 8000/5173 is ours.
  foreach ($port in 8000, 5173) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      try {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
        Write-Ok "stopped pid $($c.OwningProcess) on :$port"
      } catch { }
    }
  }
  # Celery has no port; match on its command line.
  $celery = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*celery*app.core.celery_app*" }
  foreach ($p in $celery) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
      Write-Ok "stopped celery pid $($p.ProcessId)"
    } catch { }
  }
  Write-Host ""
  Write-Host "Sentinel stopped. MySQL and Redis are Windows services and were left running." -ForegroundColor Yellow
  return
}

# ----------------------------------------------------------------- env --
Write-Step "Loading .env"
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { Write-Bad "no .env at $envFile"; exit 1 }

$envPairs = @{}
foreach ($line in Get-Content $envFile) {
  $t = $line.Trim()
  if ($t -eq "" -or $t.StartsWith("#")) { continue }
  $i = $t.IndexOf("=")
  if ($i -lt 1) { continue }
  $k = $t.Substring(0, $i).Trim()
  $v = $t.Substring($i + 1).Trim()
  # strip one layer of surrounding quotes if present
  if ($v.Length -ge 2 -and (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'")))) {
    $v = $v.Substring(1, $v.Length - 2)
  }
  $envPairs[$k] = $v
  Set-Item -Path "Env:$k" -Value $v
}
Write-Ok "$($envPairs.Count) variables loaded"

foreach ($required in "DATABASE_URL", "REDIS_URL", "SESSION_SECRET_KEY", "GROQ_API_KEY") {
  if (-not $envPairs.ContainsKey($required)) { Write-Bad "missing $required"; exit 1 }
}

# ------------------------------------------------------------ preflight --
Write-Step "Checking MySQL and Redis"
foreach ($svc in @{n="MySQL"; p=3306}, @{n="Redis"; p=6379}) {
  $ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $svc.p -InformationLevel Quiet -WarningAction SilentlyContinue
  if ($ok) {
    Write-Ok "$($svc.n) listening on $($svc.p)"
  } else {
    Write-Bad "$($svc.n) is NOT listening on $($svc.p)"
    Write-Host "        start it with:  Start-Service $($svc.n)" -ForegroundColor Yellow
    exit 1
  }
}

# ------------------------------------------------------------- migrate --
if (-not $NoMigrate) {
  Write-Step "Running migrations"
  Push-Location $backend
  try {
    python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Write-Bad "alembic failed"; exit 1 }
    Write-Ok "schema up to date"
  } finally { Pop-Location }
}

# --------------------------------------------------------------- start --
# Each process gets its own window. The child inherits this session's
# environment, so the .env above applies without re-parsing it four times.
function Start-Pane($title, $workdir, $command) {
  $inner = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location '$workdir'; $command"
  Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-Command", $inner | Out-Null
  Write-Ok "$title"
}

Write-Step "Starting Sentinel"
Start-Pane "Sentinel backend" $backend  "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
Start-Pane "Sentinel worker"  $backend  "python -m celery -A app.core.celery_app.celery_app worker --loglevel=info -Q ingestion,agents --pool=solo"
Start-Pane "Sentinel beat"    $backend  "python -m celery -A app.core.celery_app.celery_app beat --loglevel=info"
Start-Pane "Sentinel frontend" $frontend "npm run dev"

Write-Step "Waiting for the backend"
$up = $false
foreach ($i in 1..30) {
  Start-Sleep -Seconds 2
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { $up = $true; break }
  } catch { }
}

Write-Host ""
if ($up) {
  Write-Host "  Sentinel is up." -ForegroundColor Green
  Write-Host "    app       http://localhost:5173"
  Write-Host "    api       http://localhost:8000"
  Write-Host ""
  Write-Host "  Stop with:  .\run-local.ps1 -Stop" -ForegroundColor DarkGray
} else {
  Write-Bad "backend did not answer /health within 60s - check the 'Sentinel backend' window"
}
