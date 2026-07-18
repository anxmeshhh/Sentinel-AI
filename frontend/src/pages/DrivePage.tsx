import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection, DriveAnalytics, DriveFile } from "../api/types";
import { GoogleAICommand } from "../components/GoogleAICommand";

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
  const [askingFileId, setAskingFileId] = useState<string | null>(null);

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
      <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
        <p className="mb-3 text-[14px]">Google Drive isn't connected yet.</p>
        <Link to="/connections/google" className="font-mono text-[13px] font-semibold text-accent-text hover:underline">
          Connect Drive &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold text-balance">Drive</h1>
      <p className="mb-6 text-[13px] text-ink-dim">
        File name, type, and modified time only — opening a file always goes to Drive itself.
        Asking about a file's content fetches it live, never stored.
      </p>

      {analytics && (
        <div className="mb-6 rounded-md border border-border bg-surface">
          <button
            onClick={() => setAnalyticsOpen((o) => !o)}
            className="flex w-full items-center justify-between p-3.5 text-left"
          >
            <span className="font-mono text-[11.5px] font-bold uppercase tracking-wide text-ink-dim">Drive Overview</span>
            <span className={`text-[12px] text-ink-faint transition-transform ${analyticsOpen ? "rotate-180" : ""}`}>&#9660;</span>
          </button>
          {analyticsOpen && (
            <div className="border-t border-border p-3.5">
              {analytics.storage_used_bytes != null && analytics.storage_limit_bytes != null && (
                <div className="mb-3">
                  <div className="mb-1 flex justify-between text-[11px] text-ink-faint">
                    <span>Storage used</span>
                    <span>
                      {formatBytes(analytics.storage_used_bytes)} of {formatBytes(analytics.storage_limit_bytes)}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full bg-accent"
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
                    <span key={mime} className="rounded-full border border-border px-2 py-[3px] font-mono text-[10px] text-ink-faint">
                      {friendlyType(mime)} · {count}
                    </span>
                  ))}
              </div>
              {analytics.large_files.length > 0 && (
                <div>
                  <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-ink-faint">Largest files</div>
                  {analytics.large_files.slice(0, 3).map((f) => (
                    <div key={f.id} className="flex justify-between text-[11.5px] text-ink-dim">
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
          className="flex-1 rounded-md border border-border bg-surface px-3.5 py-2.5 text-[13px] outline-none focus:border-accent"
        />
        <button
          onClick={search}
          className="rounded-md border border-border bg-surface px-4 py-2.5 text-[12.5px] font-semibold text-ink-dim hover:border-accent hover:text-ink"
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
            className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] transition-colors ${
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
          className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] transition-colors ${
            sharedWithMe ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
          }`}
        >
          Shared with me
        </button>
      </div>

      {loading ? (
        <div className="text-ink-dim">Loading&hellip;</div>
      ) : files.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">
          {searched ? "No files found." : "Search your Drive above."}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {files.map((f) => (
            <div key={f.id} className="rounded-lg border border-border bg-surface p-4">
              <div className="mb-2 text-[20px]">{fileIcon(f.mime_type)}</div>
              <div className="mb-1 truncate text-[13px] font-semibold text-ink">{f.name}</div>
              <div className="text-[11px] text-ink-faint">
                {f.modified_at ? `Modified ${new Date(f.modified_at).toLocaleDateString()}` : ""}
                {f.owner && ` · ${f.owner}`}
                {f.shared && " · Shared"}
              </div>
              <div className="mt-2 flex items-center gap-3">
                <a
                  href={f.url ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-[10.5px] font-semibold text-accent-text"
                >
                  Open in Drive &rarr;
                </a>
                <button
                  onClick={() => setAskingFileId(askingFileId === f.id ? null : f.id)}
                  className="font-mono text-[10.5px] text-ink-faint underline underline-offset-2 hover:text-ink"
                >
                  Ask about this file ✨
                </button>
              </div>
              {askingFileId === f.id && (
                <div className="mt-3 -mx-4 -mb-4 rounded-b-lg border-t border-border">
                  <GoogleAICommand
                    contextPrefix={`Regarding the Drive file "${f.name}" (Drive file id: ${f.id}):`}
                    placeholder="Summarize, extract deadlines, ask anything…"
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
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
