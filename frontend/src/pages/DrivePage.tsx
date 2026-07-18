import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection, DriveFile } from "../api/types";

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

  useEffect(() => {
    api.get<Connection[]>("/connections").then((conns) => setConnected(conns.some((c) => c.provider === "google_drive")));
  }, []);

  useEffect(() => {
    if (connected) void search();
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
        File name, type, and modified time only — every result opens in Drive itself, never inside Sentinel.
      </p>

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
            <a
              key={f.id}
              href={f.url ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border border-border bg-surface p-4 hover:border-accent/50"
            >
              <div className="mb-2 text-[20px]">{fileIcon(f.mime_type)}</div>
              <div className="mb-1 truncate text-[13px] font-semibold text-ink">{f.name}</div>
              <div className="text-[11px] text-ink-faint">
                {f.modified_at ? `Modified ${new Date(f.modified_at).toLocaleDateString()}` : ""}
                {f.owner && ` · ${f.owner}`}
                {f.shared && " · Shared"}
              </div>
              <div className="mt-2 font-mono text-[10.5px] font-semibold text-accent-text">Open in Drive &rarr;</div>
            </a>
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
