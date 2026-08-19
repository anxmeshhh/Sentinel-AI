import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { DriveBrowse, DriveItem } from "../api/types";
import { DriveIcon } from "../components/ProviderIcons";
import { ActionButton, ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, Icon, LoadingBlock } from "../components/ui";

/** OneDrive as a workspace: browse, search, and act on files without leaving
 *  Sentinel. Fourth page on the shared shell - again only a work surface. */
export function OneDrivePage() {
  const [browse, setBrowse] = useState<DriveBrowse | null>(null);
  const [loading, setLoading] = useState(true);
  const [notConnected, setNotConnected] = useState(false);
  const [folderId, setFolderId] = useState<string | null>(null);
  // A simple stack, so "Back" is honest about where it goes rather than
  // guessing from parent ids that search results do not carry.
  const [trail, setTrail] = useState<{ id: string | null; name: string }[]>([{ id: null, name: "My files" }]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<DriveItem | null>(null);
  const [newFolder, setNewFolder] = useState(false);
  const [newFile, setNewFile] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (query.trim()) qs.set("q", query.trim());
    else if (folderId) qs.set("folder_id", folderId);
    api
      .get<DriveBrowse>(`/workspace/microsoft/onedrive?${qs.toString()}`)
      .then((d) => {
        setBrowse(d);
        setNotConnected(false);
        setSelected((cur) => (cur ? d.items.find((i) => i.id === cur.id) ?? null : null));
      })
      .catch(() => setNotConnected(true))
      .finally(() => setLoading(false));
  }, [folderId, query]);

  useEffect(load, [load, refreshKey]);

  function open(item: DriveItem) {
    if (item.is_folder) {
      setQuery("");
      setFolderId(item.id);
      setTrail((t) => [...t, { id: item.id, name: item.name }]);
      setSelected(null);
    } else {
      setSelected(item);
      setRenaming(false);
    }
  }

  function goTo(index: number) {
    const target = trail[index];
    setQuery("");
    setFolderId(target.id);
    setTrail(trail.slice(0, index + 1));
    setSelected(null);
  }

  function afterWrite() {
    setNewFolder(false);
    setNewFile(false);
    setRenaming(false);
    setRefreshKey((k) => k + 1);
  }

  return (
    <ProviderWorkspace
      service="microsoft_onedrive"
      title="OneDrive"
      icon={<DriveIcon />}
      parent={{ label: "Microsoft 365", to: "/connections/microsoft" }}
      refreshKey={refreshKey}
      assistant={{
        contextLabel: "Microsoft 365",
        endpointBase: "/connections/microsoft",
        placeholder: "Ask about your files…",
      }}
      quickActions={
        <>
          <Button size="sm" onClick={() => { setNewFolder((v) => !v); setNewFile(false); }}>
            New folder
          </Button>
          <Button size="sm" variant="primary" onClick={() => { setNewFile((v) => !v); setNewFolder(false); }}>
            New file
          </Button>
        </>
      }
    >
      {newFolder && <FolderComposer parentId={folderId} onDone={afterWrite} />}
      {newFile && <FileComposer parentId={folderId} onDone={afterWrite} />}

      {notConnected ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          OneDrive isn't connected yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <nav className="flex min-w-0 flex-wrap items-center gap-1 text-caption text-ink-faint">
                {trail.map((crumb, i) => (
                  <span key={`${crumb.id ?? "root"}-${i}`} className="flex items-center gap-1">
                    {i > 0 && <span aria-hidden="true">/</span>}
                    <button
                      onClick={() => goTo(i)}
                      className={i === trail.length - 1 ? "text-ink" : "underline underline-offset-2 hover:text-ink"}
                    >
                      {crumb.name}
                    </button>
                  </span>
                ))}
              </nav>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search your drive…"
                className="ml-auto min-w-[10rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1 text-caption text-ink placeholder:text-ink-faint"
              />
            </div>

            {loading ? (
              <LoadingBlock />
            ) : (browse?.items.length ?? 0) === 0 ? (
              <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-caption text-ink-faint">
                {browse?.searching ? "Nothing matched that search." : "This folder is empty."}
              </div>
            ) : (
              <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
                {browse!.items.map((i) => (
                  <li key={i.id}>
                    <button
                      onClick={() => open(i)}
                      className={`flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-surface/60 ${
                        selected?.id === i.id ? "bg-surface/70" : ""
                      }`}
                    >
                      <span className="flex-none text-ink-faint" aria-hidden="true">
                        {i.is_folder ? "▸" : "·"}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-small text-ink">{i.name}</span>
                        <span className="block truncate text-caption text-ink-faint">
                          {i.is_folder
                            ? `${i.child_count ?? 0} item${i.child_count === 1 ? "" : "s"}`
                            : formatSize(i.size)}
                          {i.shared ? " · shared" : ""}
                          {i.modified_at
                            ? ` · ${new Date(i.modified_at).toLocaleDateString([], { day: "numeric", month: "short" })}`
                            : ""}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="min-w-0">
            {!selected ? (
              <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-caption text-ink-faint">
                Select a file to see it here.
              </div>
            ) : (
              <div className="card">
                <h2 className="text-lead font-semibold leading-tight text-ink text-balance">{selected.name}</h2>
                <div className="mt-1 text-caption text-ink-faint">
                  {formatSize(selected.size)}
                  {selected.mime_type ? ` · ${selected.mime_type}` : ""}
                  {selected.modified_by ? ` · last changed by ${selected.modified_by}` : ""}
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
                  <Button size="sm" onClick={() => setRenaming((v) => !v)}>
                    {renaming ? "Cancel rename" : "Rename"}
                  </Button>
                  <ActionButton
                    actionType="onedrive.delete_item"
                    params={{ item_id: selected.id, name: selected.name, is_folder: selected.is_folder }}
                    label="Delete"
                    onDone={() => { setSelected(null); afterWrite(); }}
                  />
                  {selected.url && (
                    <a
                      href={selected.url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto inline-flex items-center gap-1 text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                    >
                      Open in OneDrive <Icon name="external" size={12} />
                    </a>
                  )}
                </div>

                {renaming && <Renamer item={selected} onDone={afterWrite} />}
              </div>
            )}
          </div>
        </div>
      )}
    </ProviderWorkspace>
  );
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function FolderComposer({ parentId, onDone }: { parentId: string | null; onDone: () => void }) {
  const [name, setName] = useState("");
  return (
    <div className="card mb-4 flex flex-wrap items-center gap-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Folder name"
        className="min-w-[12rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
      />
      <ActionButton
        actionType="onedrive.create_folder"
        params={{ name, parent_id: parentId }}
        label="Create folder"
        confirmLabel="Create"
        variant="primary"
        undoable
        disabled={name.trim().length === 0}
        onDone={onDone}
      />
    </div>
  );
}

function FileComposer({ parentId, onDone }: { parentId: string | null; onDone: () => void }) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  return (
    <div className="card mb-4">
      <div className="mb-2 text-small font-semibold text-ink">New text file</div>
      <div className="flex flex-col gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="File name (e.g. notes.txt)"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={5}
          placeholder="Contents…"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            actionType="onedrive.upload_text"
            params={{ name, content, parent_id: parentId }}
            label="Create file"
            confirmLabel="Create"
            variant="primary"
            undoable
            disabled={name.trim().length === 0 || content.length === 0}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">Text documents only — binaries aren't uploaded this way.</span>
        </div>
      </div>
    </div>
  );
}

function Renamer({ item, onDone }: { item: DriveItem; onDone: () => void }) {
  const [name, setName] = useState(item.name);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="min-w-[10rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
      />
      <ActionButton
        actionType="onedrive.rename_item"
        params={{ item_id: item.id, new_name: name }}
        label="Rename"
        confirmLabel="Rename"
        variant="primary"
        undoable
        disabled={name.trim() === item.name || name.trim().length === 0}
        onDone={onDone}
      />
    </div>
  );
}
