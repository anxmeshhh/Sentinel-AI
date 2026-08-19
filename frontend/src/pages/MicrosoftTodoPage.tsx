import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { TodoBoard, TodoTask } from "../api/types";
import { CalendarIcon } from "../components/ProviderIcons";
import { ActionButton, ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, LoadingBlock } from "../components/ui";

const VIEWS = [
  { key: "today", label: "Today" },
  { key: "upcoming", label: "Upcoming" },
  { key: "completed", label: "Completed" },
  { key: "all", label: "All" },
] as const;

type ViewKey = (typeof VIEWS)[number]["key"];

/** Overdue reads with Today, because an overdue task is what today actually
 *  owes you - hiding it in a separate tab is how it gets forgotten. */
const IN_VIEW: Record<ViewKey, (t: TodoTask) => boolean> = {
  today: (t) => t.bucket === "today" || t.bucket === "overdue",
  upcoming: (t) => t.bucket === "upcoming" || t.bucket === "someday",
  completed: (t) => t.bucket === "completed",
  all: () => true,
};

export function MicrosoftTodoPage() {
  const [board, setBoard] = useState<TodoBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [notConnected, setNotConnected] = useState(false);
  const [view, setView] = useState<ViewKey>("today");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<TodoTask | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    const qs = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
    api
      .get<TodoBoard>(`/workspace/microsoft/todo${qs}`)
      .then((d) => {
        setBoard(d);
        setNotConnected(false);
        // Keep the open task in sync with what Microsoft now reports.
        setSelected((cur) => (cur ? d.tasks.find((t) => t.id === cur.id) ?? null : null));
      })
      .catch(() => setNotConnected(true))
      .finally(() => setLoading(false));
  }, [query]);

  useEffect(load, [load, refreshKey]);

  function afterWrite() {
    setCreating(false);
    setEditing(false);
    setRefreshKey((k) => k + 1);
  }

  const tasks = (board?.tasks ?? []).filter(IN_VIEW[view]);
  const defaultList = board?.lists.find((l) => l.default) ?? board?.lists[0];

  return (
    <ProviderWorkspace
      service="microsoft_todo"
      title="Microsoft To Do"
      icon={<CalendarIcon />}
      parent={{ label: "Microsoft 365", to: "/connections/microsoft" }}
      refreshKey={refreshKey}
      assistant={{
        contextLabel: "Microsoft 365",
        endpointBase: "/connections/microsoft",
        placeholder: "Ask about your tasks…",
      }}
      quickActions={
        <Button size="sm" variant="primary" onClick={() => { setCreating((v) => !v); setEditing(false); }}>
          {creating ? "Close" : "New task"}
        </Button>
      }
    >
      {creating && defaultList && <TaskComposer listId={defaultList.id} onDone={afterWrite} />}

      {notConnected ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          Microsoft To Do isn't connected yet.
        </div>
      ) : (
        <>
          {(board?.counts.overdue ?? 0) > 0 && (
            <div className="mb-4 rounded-md border border-crit/40 bg-crit/5 px-3 py-2">
              <span className="text-caption font-semibold text-crit">
                {board!.counts.overdue} overdue task{board!.counts.overdue === 1 ? "" : "s"}
              </span>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            {/* ---- list ---- */}
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {VIEWS.map((v) => (
                  <button
                    key={v.key}
                    onClick={() => setView(v.key)}
                    className={`rounded-md px-2.5 py-1 text-caption transition-colors ${
                      view === v.key ? "bg-surface-2 font-semibold text-ink" : "text-ink-faint hover:text-ink"
                    }`}
                  >
                    {v.label}
                    {v.key === "today" && (board?.counts.today ?? 0) + (board?.counts.overdue ?? 0) > 0 && (
                      <span className="ml-1 tabular-nums text-ink-faint">
                        {(board?.counts.today ?? 0) + (board?.counts.overdue ?? 0)}
                      </span>
                    )}
                  </button>
                ))}
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search tasks…"
                  className="ml-auto min-w-[9rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1 text-caption text-ink placeholder:text-ink-faint"
                />
              </div>

              {loading ? (
                <LoadingBlock />
              ) : tasks.length === 0 ? (
                <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-caption text-ink-faint">
                  Nothing here.
                </div>
              ) : (
                <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
                  {tasks.map((t) => (
                    <li key={t.id} className="flex items-start gap-2 px-3 py-2.5">
                      {/* Completing is a write, so it is an ActionButton like
                          everything else - not a checkbox that silently PATCHes. */}
                      <span className="flex-none pt-0.5">
                        <ActionButton
                          actionType="todo.complete_task"
                          params={{ list_id: t.list_id, task_id: t.id, completed: !t.completed, title: t.title }}
                          label={t.completed ? "Reopen" : "Done"}
                          undoable
                          onDone={afterWrite}
                        />
                      </span>
                      <button onClick={() => { setSelected(t); setEditing(false); }} className="min-w-0 flex-1 text-left">
                        <span
                          className={`block truncate text-small ${
                            t.completed ? "text-ink-faint line-through" : "font-medium text-ink"
                          }`}
                        >
                          {t.title}
                        </span>
                        <span className="block truncate text-caption text-ink-faint">
                          {t.due_at
                            ? `${t.bucket === "overdue" ? "Overdue · " : ""}${new Date(t.due_at).toLocaleDateString([], {
                                day: "numeric", month: "short",
                              })}`
                            : "No due date"}
                          {t.importance === "high" ? " · high" : ""}
                          {t.list ? ` · ${t.list}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* ---- detail ---- */}
            <div className="min-w-0">
              {!selected ? (
                <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-caption text-ink-faint">
                  Select a task to see it here.
                </div>
              ) : (
                <div className="card">
                  <h2 className="text-lead font-semibold leading-tight text-ink text-balance">{selected.title}</h2>
                  <div className="mt-1 text-caption text-ink-faint">
                    {selected.due_at
                      ? `Due ${new Date(selected.due_at).toLocaleDateString([], {
                          weekday: "short", day: "numeric", month: "short",
                        })}`
                      : "No due date"}
                    {selected.importance === "high" ? " · high importance" : ""}
                    {selected.list ? ` · ${selected.list}` : ""}
                  </div>
                  {selected.notes && (
                    <p className="mt-2 whitespace-pre-wrap text-small leading-relaxed text-ink-dim">{selected.notes}</p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
                    <Button size="sm" onClick={() => setEditing((v) => !v)}>
                      {editing ? "Cancel edit" : "Edit"}
                    </Button>
                    <ActionButton
                      actionType="todo.delete_task"
                      params={{ list_id: selected.list_id, task_id: selected.id, title: selected.title }}
                      label="Delete"
                      undoable
                      onDone={() => { setSelected(null); afterWrite(); }}
                    />
                  </div>

                  {editing && <TaskEditor task={selected} onDone={afterWrite} />}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </ProviderWorkspace>
  );
}

function toDateInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function TaskComposer({ listId, onDone }: { listId: string; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [importance, setImportance] = useState("normal");
  const [notes, setNotes] = useState("");

  return (
    <div className="card mb-4">
      <div className="mb-2 text-small font-semibold text-ink">New task</div>
      <div className="flex flex-col gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="What needs doing?"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap gap-2">
          <label className="text-caption text-ink-faint">
            Due
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="ml-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            />
          </label>
          <label className="text-caption text-ink-faint">
            Priority
            <select
              value={importance}
              onChange={(e) => setImportance(e.target.value)}
              className="ml-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
          </label>
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Notes (optional)"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex items-center gap-2">
          <ActionButton
            actionType="todo.create_task"
            params={{
              list_id: listId,
              title,
              due_at: due ? new Date(`${due}T09:00:00`).toISOString() : null,
              importance,
              notes,
            }}
            label="Add task"
            confirmLabel="Add"
            variant="primary"
            undoable
            disabled={title.trim().length === 0}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">Added to your real To Do list. Undoable.</span>
        </div>
      </div>
    </div>
  );
}

function TaskEditor({ task, onDone }: { task: TodoTask; onDone: () => void }) {
  const [title, setTitle] = useState(task.title);
  const [due, setDue] = useState(toDateInput(task.due_at));
  const [importance, setImportance] = useState(task.importance);

  const hadDue = Boolean(task.due_at);
  const clearDue = hadDue && due === "";
  const changed = title !== task.title || due !== toDateInput(task.due_at) || importance !== task.importance;

  return (
    <div className="mt-3 rounded-md border border-border p-3">
      <div className="flex flex-col gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
        />
        <div className="flex flex-wrap gap-2">
          <label className="text-caption text-ink-faint">
            Due
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="ml-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            />
          </label>
          <label className="text-caption text-ink-faint">
            Priority
            <select
              value={importance}
              onChange={(e) => setImportance(e.target.value)}
              className="ml-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
          </label>
        </div>
        <div className="flex items-center gap-2">
          <ActionButton
            actionType="todo.update_task"
            params={{
              list_id: task.list_id,
              task_id: task.id,
              title,
              due_at: clearDue || !due ? null : new Date(`${due}T09:00:00`).toISOString(),
              clear_due: clearDue,
              importance,
            }}
            label="Save changes"
            confirmLabel="Apply"
            variant="primary"
            undoable
            disabled={!changed}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">Undoable — the previous values are kept.</span>
        </div>
      </div>
    </div>
  );
}
