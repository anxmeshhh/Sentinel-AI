import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useState } from "react";

import { ButtonGhost, ButtonPrimary } from "@/components/sentinel/primitives";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/login")({
  head: () => ({ meta: [{ title: "Sign in — Sentinel" }] }),
  component: LoginPage,
});

/** Two ways in, because the backend supports both: a password, or a one-time
 *  code mailed to the address. The OTP path is also what verifies a new
 *  account, so it is not a secondary nicety. */
type Mode = "password" | "otp";

function LoginPage() {
  const { login, requestOtp, verifyOtp } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>, thenHome = true) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (thenHome) router.navigate({ to: "/" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Sign in to Sentinel"
      subtitle="Sentinel reads the tools you already work in and tells you what actually needs attention."
      footer={
        <>
          No account yet?{" "}
          <Link to="/signup" className="text-ink underline underline-offset-2">
            Create one
          </Link>
        </>
      }
    >
      <Field label="Email">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          placeholder="you@company.com"
          className="input"
        />
      </Field>

      {mode === "password" ? (
        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="input"
            onKeyDown={(e) => {
              if (e.key === "Enter" && email && password) void run(() => login(email, password));
            }}
          />
        </Field>
      ) : sent ? (
        <Field label="Code from your email">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            placeholder="6-digit code"
            className="input font-mono tracking-[0.2em]"
          />
        </Field>
      ) : null}

      {error && <p className="t-caption" style={{ color: "var(--crit)" }}>{error}</p>}

      <div className="flex flex-wrap items-center gap-2">
        {mode === "password" ? (
          <ButtonPrimary
            disabled={busy || !email || !password}
            onClick={() => void run(() => login(email, password))}
          >
            {busy ? "Signing in…" : "Sign in"}
          </ButtonPrimary>
        ) : sent ? (
          <ButtonPrimary
            disabled={busy || code.length < 4}
            onClick={() => void run(() => verifyOtp(email, "login", code))}
          >
            {busy ? "Verifying…" : "Verify code"}
          </ButtonPrimary>
        ) : (
          <ButtonPrimary
            disabled={busy || !email}
            onClick={() =>
              void run(async () => {
                await requestOtp(email, "login");
                setSent(true);
              }, false)
            }
          >
            {busy ? "Sending…" : "Email me a code"}
          </ButtonPrimary>
        )}

        <ButtonGhost
          onClick={() => {
            setMode(mode === "password" ? "otp" : "password");
            setSent(false);
            setError(null);
          }}
        >
          {mode === "password" ? "Use a code instead" : "Use a password instead"}
        </ButtonGhost>
      </div>
    </AuthLayout>
  );
}

/* ------------------------------------------------------------------ shared */

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
      <div className="mb-8 flex items-center gap-2.5">
        <span className="relative h-[13px] w-[13px] rounded-full border border-ink" aria-hidden="true">
          <span className="absolute inset-[4px] rounded-full" style={{ background: "var(--brand)" }} />
        </span>
        <span className="t-caption font-medium text-ink">Sentinel</span>
      </div>

      <h1 className="t-h2 font-medium text-ink">{title}</h1>
      <p className="t-caption mt-1.5 text-balance text-ink-dim">{subtitle}</p>

      <div className="mt-8 flex flex-col gap-4">{children}</div>

      {footer && <p className="t-caption mt-8 text-ink-faint">{footer}</p>}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="t-micro uppercase tracking-[0.06em] text-ink-faint">{label}</span>
      {children}
    </label>
  );
}
