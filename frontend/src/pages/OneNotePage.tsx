import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { NoteBrowse, NotePage } from "../api/types";
import { MailIcon } from "../components/ProviderIcons";
import { MICROSOFT_ASSISTANT } from "../components/workspace/assistantConfigs";
import { ActionButton, ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, Icon, LoadingBlock } from "../components/ui";

/** OneNote as a workspace: notebook → section → page, read the page, add to it,
 *  or write a new one. Fifth page on the shared shell. */
export function OneNotePage() {
  const [browse, setBrowse] = useState<NoteBrowse | null>(null);
  const [loading, setLoading] = useState(true);
  const [notConnected, setNotConnected] = useState(false);
  const [notebookId, setNotebookId] = useState<string | null>(null);
  const [sectionId, setSectionId] = useState<string | null>(null);
  const [selected, setSelected] = useState<NotePage | null>(null);
  const [text, setText] = useState<string | "loading" | { error: string } | null>(null);
  const [composing, setComposing] = useState(false);
  const [appending, setAppending] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (notebookId) qs.set("notebook_id", notebookId);
    if (sectionId) qs.set("section_id", sectionId);
    api
      .get<NoteBrowse>(`/workspace/microsoft/onenote?${qs.toString()}`)
      .then((d) => {
        setBrowse(d);
        setNotConnected(false);
        // Open the first notebook automatically - a browser that starts empty
        // makes the user do a click that has only one possible answer.
        if (!notebookId && d.notebooks.length > 0) setNotebookId(d.notebooks[0].id);
      })
      .catch(() => setNotConnected(true))
      .finally(() => setLoading(false));
  }, [notebookId, sectionId]);

  useEffect(load, [load, refreshKey]);

  function openPage(page: NotePage) {
    setSelected(page);
    setAppending(false);
    setText("loading");
    api
      .get<{ text: string }>(`/workspace/microsoft/onenote/pages/${page.id}`)
      .then((d) => setText(d.text))
      .catch((e) => setText({ error: e instanceof Error ? e.message : "Couldn't open that page" }));
  }

  function afterWrite() {
    setComposing(false);
    setAppending(false);
    setRefreshKey((k) => k + 1);
    if (selected) {
      api
        .get<{ text: string }>(`/workspace/microsoft/onenote/pages/${selected.id}`)
        .then((d) => setText(d.text))
        .catch(() => undefined);
    }
  }

  return (
    <ProviderWorkspace
      service="microsoft_onenote"
      title="OneNote"
      icon={<MailIcon />}
      parent={{ label: "Microsoft 365", to: "/connections/microsoft" }}
      refreshKey={refreshKey}
      assistant={MICROSOFT_ASSISTANT}
      activitySources={["OneNote"]}
      quickActions={
        <button
          onClick={() => setComposing((v) => !v)}
          disabled={!sectionId}
          title={sectionId ? undefined : "Choose a section first"}
          className="btn-primary disabled:opacity-50"
        >
          {composing ? "Close" : "New note"}
        </button>
      }
    >
      {composing && sectionId && <PageComposer sectionId={sectionId} onDone={afterWrite} />}

      {notConnected ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          OneNote isn't connected yet.
        </div>
      ) : loading && !browse ? (
        <LoadingBlock />
      ) : (browse?.notebooks.length ?? 0) === 0 ? (
        <div className="card">
          <div className="text-small font-semibold text-ink">No notebooks yet</div>
          <p className="mt-1 text-caption text-ink-faint">
            OneNote needs a notebook and a section before you can write a note. Create one here.
          </p>
          <div className="mt-3">
            <NotebookComposer onDone={afterWrite} />
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="min-w-0">
            <Picker
              label="Notebook"
              options={browse!.notebooks.map((n) => ({ id: n.id, name: n.name }))}
              value={notebookId}
              onChange={(id) => { setNotebookId(id); setSectionId(null); setSelected(null); }}
            />
            {notebookId && browse!.sections.length > 0 && (
              <Picker
                label="Section"
                options={browse!.sections.map((s) => ({ id: s.id, name: s.name }))}
                value={sectionId}
                onChange={(id) => { setSectionId(id); setSelected(null); }}
              />
            )}
            {notebookId && browse!.sections.length === 0 && (
              <div className="mb-2 rounded-md border border-dashed border-border px-3 py-3">
                <div className="text-caption text-ink-faint">
                  This notebook has no sections. Notes live in sections, so add one first.
                </div>
                <div className="mt-2">
                  <SectionComposer notebookId={notebookId} onDone={afterWrite} />
                </div>
              </div>
            )}

            {sectionId && (
              browse!.pages.length === 0 ? (
                <div className="mt-2 rounded-md border border-dashed border-border px-4 py-8 text-center text-caption text-ink-faint">
                  No pages in this section yet.
                </div>
              ) : (
                <ul className="mt-2 flex flex-col divide-y divide-border rounded-md border border-border">
                  {browse!.pages.map((p) => (
                    <li key={p.id}>
                      <button
                        onClick={() => openPage(p)}
                        className={`flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition-colors hover:bg-surface/60 ${
                          selected?.id === p.id ? "bg-surface/70" : ""
                        }`}
                      >
                        <span className="truncate text-small text-ink">{p.title}</span>
                        {p.modified_at && (
                          <span className="text-caption text-ink-faint">
                            {new Date(p.modified_at).toLocaleDateString([], { day: "numeric", month: "short" })}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )
            )}
          </div>

          <div className="min-w-0">
            {!selected ? (
              <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-caption text-ink-faint">
                {sectionId ? "Select a page to read it here." : "Choose a section to see its pages."}
              </div>
            ) : (
              <div className="card">
                <h2 className="text-lead font-semibold leading-tight text-ink text-balance">{selected.title}</h2>

                <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
                  <Button size="sm" onClick={() => setAppending((v) => !v)}>
                    {appending ? "Cancel" : "Add to this note"}
                  </Button>
                  {selected.url && (
                    <a
                      href={selected.url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto inline-flex items-center gap-1 text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                    >
                      Open in OneNote <Icon name="external" size={12} />
                    </a>
                  )}
                </div>

                {appending && <Appender page={selected} onDone={afterWrite} />}

                <div className="mt-3">
                  {text === "loading" ? (
                    <LoadingBlock />
                  ) : text && typeof text === "object" && "error" in text ? (
                    <p className="text-caption text-crit">{text.error}</p>
                  ) : typeof text === "string" ? (
                    <p className="whitespace-pre-wrap text-small leading-relaxed text-ink-dim">
                      {text || "This page is empty."}
                    </p>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </ProviderWorkspace>
  );
}

function Picker({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: string; name: string }[];
  value: string | null;
  onChange: (id: string) => void;
}) {
  return (
    <label className="mb-2 block text-caption text-ink-faint">
      {label}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
      >
        <option value="" disabled>
          Choose a {label.toLowerCase()}…
        </option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function NotebookComposer({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Notebook name"
        className="min-w-[11rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
      />
      <ActionButton
        actionType="onenote.create_notebook"
        params={{ name }}
        label="Create notebook"
        confirmLabel="Create"
        variant="primary"
        disabled={name.trim().length === 0}
        onDone={onDone}
      />
    </div>
  );
}

function SectionComposer({ notebookId, onDone }: { notebookId: string; onDone: () => void }) {
  const [name, setName] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Section name"
        className="min-w-[10rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
      />
      <ActionButton
        actionType="onenote.create_section"
        params={{ notebook_id: notebookId, name }}
        label="Create section"
        confirmLabel="Create"
        variant="primary"
        disabled={name.trim().length === 0}
        onDone={onDone}
      />
    </div>
  );
}

function PageComposer({ sectionId, onDone }: { sectionId: string; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  return (
    <div className="card mb-4">
      <div className="mb-2 text-small font-semibold text-ink">New note</div>
      <div className="flex flex-col gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder="Write your note…"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex items-center gap-2">
          <ActionButton
            actionType="onenote.create_page"
            params={{ section_id: sectionId, title, body }}
            label="Create note"
            confirmLabel="Create"
            variant="primary"
            undoable
            disabled={title.trim().length === 0}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">Added to the selected section. Undoable.</span>
        </div>
      </div>
    </div>
  );
}

function Appender({ page, onDone }: { page: NotePage; onDone: () => void }) {
  const [content, setContent] = useState("");
  return (
    <div className="mt-3 rounded-md border border-border p-3">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={3}
        placeholder="Add to the end of this note…"
        className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <ActionButton
          actionType="onenote.append_page"
          params={{ page_id: page.id, content, title: page.title }}
          label="Add to note"
          confirmLabel="Add"
          variant="primary"
          undoable
          disabled={content.trim().length === 0}
          onDone={onDone}
        />
        <span className="text-caption text-ink-faint">
          Undo restores the page as it was before this addition.
        </span>
      </div>
    </div>
  );
}
