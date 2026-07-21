import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection, DriveAnalytics, DriveFile } from "../api/types";
import { BackNav } from "../components/BackNav";
import { GoogleAICommand } from "../components/GoogleAICommand";
import { LoadingBlock } from "../components/ui";

const MIME_FILTERS = [
  { key: "", label: "All" },
  { key: "document", label: "Docs" },
  { key: "spreadsheet", label: "Sheets" },
  { key: "presentation", label: "Slides" },
  { key: "pdf", label: "PDFs" },
  { key: "folder", label: "Folders" },
];

export function DrivePage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [mimeType, setMimeType] = useState("");
  const [sharedWithMe, setSharedWithMe] = useState(false);
  const [files, setFiles] = useState<DriveFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedFile, setSelectedFile] = useState<DriveFile | null>(null);

  const [analytics, setAnalytics] = useState<DriveAnalytics | null>(null);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);

  useEffect(() => {
    api.get<Connection[]>("/connections").then((conns) => setConnected(conns.some((c) => c.provider === "google_drive")));
  }, []);

  useEffect(() => {
    if (!connected) return;
    void search();
    api
      .get<DriveAnalytics>("/drive/analytics")
      .then(setAnalytics)
      .catch(() => setAnalytics(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  async function search() {
    setLoading(true);
    setSearched(true);
    try {
      const qs = new URLSearchParams({ limit: "30" });
      if (query.trim()) qs.set("query", query.trim());
      if (mimeType) qs.set("mime_type", mimeType);
      if (sharedWithMe) qs.set("shared_with_me", "true");
      const data = await api.get<DriveFile[]>(`/drive/search?${qs.toString()}`);
      setFiles(data);
    } catch {
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }

  if (connected === false) {
    return (
      <div className="max-w-lg rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
        <BackNav
          back={{ to: "/connections/google", label: "Google Workspace" }}
          crumbs={[{ label: "Dashboard", to: "/" }, { label: "Google", to: "/connections/google" }, { label: "Drive" }]}
        />
        <p className="mb-3 text-lead">Google Drive isn't connected yet.</p>
        <Link to="/connections/google" className="text-body font-semibold text-accent-text hover:underline">
          Connect Drive &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-6xl">
      <BackNav
        back={{ to: "/connections/google", label: "Google Workspace" }}
        crumbs={[{ label: "Dashboard", to: "/" }, { label: "Google", to: "/connections/google" }, { label: "Drive" }]}
      />
      <p className="eyebrow mb-2.5">Personal</p>
      <div className="section-head">
        <h1>Drive</h1>
        <p>
          File name, type, and modified time only — opening a file always goes to Drive itself.
        Asking about a file's content fetches it live, never stored.
        </p>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          {analytics && (
            <div className="mb-6 card">
              <button
                onClick={() => setAnalyticsOpen((o) => !o)}
                className="flex w-full items-center justify-between p-3.5 text-left"
              >
                <span className="label-sub font-bold text-ink-dim">Drive Overview</span>
                <span className={`text-small text-ink-faint transition-transform ${analyticsOpen ? "rotate-180" : ""}`}>&#9660;</span>
              </button>
              {analyticsOpen && (
                <div className="border-t border-border p-3.5">
                  {analytics.storage_used_bytes != null && analytics.storage_limit_bytes != null && (
                    <div className="mb-3">
                      <div className="mb-1 flex justify-between text-caption text-ink-faint">
                        <span>Storage used</span>
                        <span>
                          {formatBytes(analytics.storage_used_bytes)} of {formatBytes(analytics.storage_limit_bytes)}
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                        <div
                          className="h-full rounded-full bg-brand"
                          style={{ width: `${Math.min(100, (analytics.storage_used_bytes / analytics.storage_limit_bytes) * 100)}%` }}
                        />
                      </div>
                    </div>
                  )}
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {Object.entries(analytics.type_counts)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 6)
                      .map(([mime, count]) => (
                        <span key={mime} className="rounded-full border border-border px-2 py-[3px] text-micro text-ink-faint">
                          {friendlyType(mime)} · {count}
                        </span>
                      ))}
                  </div>
                  {analytics.large_files.length > 0 && (
                    <div>
                      <div className="label-sub mb-1">Largest files</div>
                      {analytics.large_files.slice(0, 3).map((f) => (
                        <div key={f.id} className="flex justify-between text-caption text-ink-dim">
                          <span className="truncate">{f.name}</span>
                          <span className="flex-none text-ink-faint">{f.size_bytes ? formatBytes(f.size_bytes) : ""}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="mb-4 flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder="Search Drive by name or content…"
              className="flex-1 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <button
              onClick={search}
              className="card px-4 py-2.5 text-small font-semibold text-ink-dim hover:border-accent hover:text-ink"
            >
              Search
            </button>
          </div>

          <div className="mb-5 flex flex-wrap items-center gap-1.5">
            {MIME_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => {
                  setMimeType(f.key);
                  setTimeout(search, 0);
                }}
                className={`rounded-full border px-3 py-1.5 font-mono text-caption transition-colors ${
                  mimeType === f.key ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
                }`}
              >
                {f.label}
              </button>
            ))}
            <button
              onClick={() => {
                setSharedWithMe((s) => !s);
                setTimeout(search, 0);
              }}
              className={`rounded-full border px-3 py-1.5 font-mono text-caption transition-colors ${
                sharedWithMe ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
              }`}
            >
              Shared with me
            </button>
          </div>

          {loading ? (
            <LoadingBlock />
          ) : files.length === 0 ? (
            <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
              {searched ? "No files found." : "Search your Drive above."}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {files.map((f) => (
                <div
                  key={f.id}
                  className={`rounded-lg border p-4 transition-colors ${
                    selectedFile?.id === f.id ? "border-accent bg-accent/5" : "border-border bg-surface"
                  }`}
                >
                  <div className="mb-2 text-h2">{fileIcon(f.mime_type)}</div>
                  <div className="mb-1 truncate text-body font-semibold text-ink">{f.name}</div>
                  <div className="text-caption text-ink-faint">
                    {f.modified_at ? `Modified ${new Date(f.modified_at).toLocaleDateString()}` : ""}
                    {f.owner && ` · ${f.owner}`}
                    {f.shared && " · Shared"}
                  </div>
                  <div className="mt-2 flex items-center gap-3">
                    <a
                      href={f.url ?? "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-caption font-semibold text-accent-text"
                    >
                      Open in Drive &rarr;
                    </a>
                    <button
                      onClick={() => setSelectedFile(selectedFile?.id === f.id ? null : f)}
                      className={`font-mono text-caption underline underline-offset-2 ${
                        selectedFile?.id === f.id ? "text-accent-text" : "text-ink-faint hover:text-ink"
                      }`}
                    >
                      Ask about this file ✨
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {selectedFile && (
          <div className="w-full flex-none lg:sticky lg:top-6 lg:h-[calc(100vh-8rem)] lg:w-[380px]">
            <div className="flex h-full flex-col card">
              <div className="flex items-center justify-between border-b border-border p-3.5">
                <div className="min-w-0">
                  <div className="mb-0.5 flex items-center gap-1.5 text-caption text-ink-faint">
                    <span>{fileIcon(selectedFile.mime_type)}</span>
                    <span>File</span>
                  </div>
                  <div className="truncate text-body font-semibold text-ink">{selectedFile.name}</div>
                </div>
                <button
                  onClick={() => setSelectedFile(null)}
                  aria-label="Close"
                  className="ml-2 flex-none rounded-md px-2 py-1 text-body text-ink-faint hover:bg-surface-2 hover:text-ink"
                >
                  &times;
                </button>
              </div>
              <div className="border-b border-border p-3.5">
                <a
                  href={selectedFile.url ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-caption font-semibold text-accent-text hover:underline"
                >
                  Open in Drive &rarr;
                </a>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <GoogleAICommand
                  contextPrefix={`Regarding the Drive file "${selectedFile.name}" (Drive file id: ${selectedFile.id}):`}
                  placeholder="Summarize, extract deadlines, ask anything…"
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function fileIcon(mimeType: string | null): string {
  if (!mimeType) return "📄";
  if (mimeType.includes("folder")) return "📁";
  if (mimeType.includes("spreadsheet")) return "📊";
  if (mimeType.includes("presentation")) return "📽️";
  if (mimeType.includes("document")) return "📝";
  if (mimeType === "application/pdf") return "📕";
  if (mimeType.startsWith("image/")) return "🖼️";
  return "📄";
}

function friendlyType(mime: string): string {
  if (mime.includes("folder")) return "Folders";
  if (mime.includes("spreadsheet")) return "Sheets";
  if (mime.includes("presentation")) return "Slides";
  if (mime.includes("wordprocessingml") || mime.includes("google-apps.document")) return "Docs";
  if (mime === "application/pdf") return "PDFs";
  if (mime.startsWith("video/")) return "Videos";
  if (mime.startsWith("image/")) return "Images";
  if (mime.includes("zip") || mime.includes("compressed")) return "Archives";
  return "Other";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
