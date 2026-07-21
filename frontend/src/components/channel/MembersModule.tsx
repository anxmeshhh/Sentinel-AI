import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { MemberReadiness, TeamMember, WorkspaceMember } from "../../api/types";
import { PROVIDER_LABEL } from "../ChannelSetupChecklist";
import { InviteModal } from "../InviteModal";
import { LoadingBlock } from "../ui";

/** Who is in this channel, and - for admins - how far along their setup is.
 *
 * Readiness here is a state per provider. It is never a credential, and
 * there is no control that would let an admin act on someone else's
 * connection. */
export function MembersModule({ teamId, isAdmin, channelName, workspaceId }: { teamId: string; isAdmin: boolean; channelName: string; workspaceId: string }) {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [roster, setRoster] = useState<MemberReadiness[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [inviting, setInviting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMembers(await api.get<TeamMember[]>(`/teams/${teamId}/members`));
      if (isAdmin) {
        try {
          setRoster(await api.get<MemberReadiness[]>(`/teams/${teamId}/readiness/roster`));
        } catch {
          setRoster([]);
        }
      }
    } finally {
      setLoading(false);
    }
  }, [teamId, isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock />;

  const readinessByUser = new Map(roster.map((r) => [r.user_id, r]));

  return (
    <div className="rule-rows">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-caption text-ink-faint">
          {members.length} member{members.length === 1 ? "" : "s"}
        </span>
        <div className="flex items-center gap-3">
          {isAdmin && <AddMemberPicker teamId={teamId} workspaceId={workspaceId} members={members} onAdded={load} />}
          <button
            onClick={() => setInviting(true)}
            className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Invite to this channel
          </button>
        </div>
      </div>
      {inviting && (
        <InviteModal scope={{ type: "team", id: teamId }} label={`#${channelName}`} onClose={() => setInviting(false)} />
      )}
      {members.map((m) => {
        const readiness = readinessByUser.get(m.user_id);
        const pending = readiness?.requirements.filter((r) => r.state !== "ready") ?? [];
        return (
          <div key={m.user_id} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-small text-ink">{m.name}</div>
              <div className="truncate text-caption text-ink-faint">{m.email}</div>
              {readiness && pending.length > 0 && (
                <div className="mt-1 text-caption text-watch">
                  Needs: {pending.map((r) => PROVIDER_LABEL[r.provider] ?? r.provider).join(", ")}
                </div>
              )}
            </div>
            <div className="flex flex-none items-center gap-2">
              {readiness && (
                <span className={`font-mono text-micro ${readiness.is_ready ? "text-good" : "text-watch"}`}>
                  {readiness.is_ready ? "ready" : "setup pending"}
                </span>
              )}
              <span
                className={`rounded-full px-2 py-0.5 font-mono text-micro ${
                  m.channel_role === "channel_admin" ? "bg-accent/15 text-accent-text" : "text-ink-faint"
                }`}
              >
                {m.channel_role === "channel_admin" ? "admin" : "member"}
              </span>
              {isAdmin && (
                <>
                  <button
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api.patch(`/teams/${teamId}/members/${m.user_id}/role`, {
                          channel_role: m.channel_role === "channel_admin" ? "channel_member" : "channel_admin",
                        });
                        await load();
                      } catch (e) {
                        alert(e instanceof ApiError ? e.message : "Failed to update role");
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                    className="text-caption text-ink-faint underline hover:text-ink"
                  >
                    {m.channel_role === "channel_admin" ? "Demote" : "Promote"}
                  </button>
                  <button
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api.delete(`/teams/${teamId}/members/${m.user_id}`);
                        await load();
                      } catch (e) {
                        alert(e instanceof ApiError ? e.message : "Failed to remove member");
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                    className="text-caption text-ink-faint underline hover:text-crit"
                  >
                    Remove
                  </button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}


/** Admin adds an existing workspace member directly - the fast path when
 *  the person is already in the Group. People outside the workspace still
 *  come in through invite links, where account reuse lives. */
function AddMemberPicker({
  teamId,
  workspaceId,
  members,
  onAdded,
}: {
  teamId: string;
  workspaceId: string;
  members: TeamMember[];
  onAdded: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<WorkspaceMember[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.get<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`).then(setCandidates).catch(() => setCandidates([]));
  }, [open, workspaceId]);

  const inChannel = new Set(members.map((m) => m.user_id));
  const addable = candidates.filter((c) => !inChannel.has(c.user_id));

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink">
        Add member
      </button>
    );
  }

  return (
    <div className="relative">
      <button onClick={() => setOpen(false)} className="text-caption text-ink-dim underline underline-offset-2 hover:text-ink">
        Close
      </button>
      <div className="absolute right-0 top-7 z-20 w-72 rounded-md border border-border bg-surface-2 p-2 shadow-overlay">
        {addable.length === 0 ? (
          <p className="px-2 py-1.5 text-caption text-ink-faint">
            Everyone in this workspace is already in the channel — use an invite link for new people.
          </p>
        ) : (
          addable.map((c) => (
            <button
              key={c.user_id}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post(`/teams/${teamId}/members`, { user_id: c.user_id });
                  await onAdded();
                  setOpen(false);
                } catch (e) {
                  alert(e instanceof ApiError ? e.message : "Failed to add");
                } finally {
                  setBusy(false);
                }
              }}
              className="block w-full rounded-sm px-2 py-1.5 text-left transition-colors hover:bg-surface-3 disabled:opacity-50"
            >
              <span className="block truncate text-caption text-ink">{c.name}</span>
              <span className="block truncate text-micro text-ink-faint">{c.email}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
