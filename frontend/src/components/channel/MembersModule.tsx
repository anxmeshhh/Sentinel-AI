import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { MemberReadiness, TeamMember } from "../../api/types";
import { PROVIDER_LABEL } from "../ChannelSetupChecklist";
import { InviteModal } from "../InviteModal";

/** Who is in this channel, and - for admins - how far along their setup is.
 *
 * Readiness here is a state per provider. It is never a credential, and
 * there is no control that would let an admin act on someone else's
 * connection. */
export function MembersModule({ teamId, isAdmin, channelName }: { teamId: string; isAdmin: boolean; channelName: string }) {
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

  if (loading) return <div className="text-[13px] text-ink-dim">Loading&hellip;</div>;

  const readinessByUser = new Map(roster.map((r) => [r.user_id, r]));

  return (
    <div className="flex flex-col gap-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11.5px] text-ink-faint">
          {members.length} member{members.length === 1 ? "" : "s"}
        </span>
        <button
          onClick={() => setInviting(true)}
          className="text-[11px] text-ink-faint underline underline-offset-2 hover:text-ink"
        >
          Invite to this channel
        </button>
      </div>
      {inviting && (
        <InviteModal scope={{ type: "team", id: teamId }} label={`#${channelName}`} onClose={() => setInviting(false)} />
      )}
      {members.map((m) => {
        const readiness = readinessByUser.get(m.user_id);
        const pending = readiness?.requirements.filter((r) => r.state !== "ready") ?? [];
        return (
          <div key={m.user_id} className="flex items-start justify-between gap-3 rounded-md border border-border bg-surface px-3 py-2.5">
            <div className="min-w-0">
              <div className="truncate text-[12.5px] text-ink">{m.name}</div>
              <div className="truncate text-[10.5px] text-ink-faint">{m.email}</div>
              {readiness && pending.length > 0 && (
                <div className="mt-1 text-[10.5px] text-watch">
                  Needs: {pending.map((r) => PROVIDER_LABEL[r.provider] ?? r.provider).join(", ")}
                </div>
              )}
            </div>
            <div className="flex flex-none items-center gap-2">
              {readiness && (
                <span className={`font-mono text-[10px] ${readiness.is_ready ? "text-good" : "text-watch"}`}>
                  {readiness.is_ready ? "ready" : "setup pending"}
                </span>
              )}
              <span
                className={`rounded-full px-2 py-0.5 font-mono text-[10px] ${
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
                    className="text-[10.5px] text-ink-faint underline hover:text-ink"
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
                    className="text-[10.5px] text-ink-faint underline hover:text-crit"
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
