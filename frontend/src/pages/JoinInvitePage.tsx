import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { InviteAcceptResult, InvitePreview } from "../api/types";
import { AuthLayout, ErrorText, primaryButtonClass } from "../components/AuthLayout";
import { useAuth } from "../context/AuthContext";
import { useWorkspace } from "../context/WorkspaceContext";

export function JoinInvitePage() {
  const { token } = useParams<{ token: string }>();
  const { user, loading: authLoading } = useAuth();
  const { setActiveId, refresh } = useWorkspace();
  const navigate = useNavigate();

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    api
      .get<InvitePreview>(`/invites/${token}`)
      .then(setPreview)
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : "This invite couldn't be loaded"));
  }, [token]);

  async function handleJoin() {
    if (!token) return;
    setJoining(true);
    setJoinError(null);
    try {
      const result = await api.post<InviteAcceptResult>(`/invites/${token}/accept`);
      await refresh();
      setActiveId(result.workspace_id);
      navigate("/");
    } catch (e) {
      setJoinError(e instanceof ApiError ? e.message : "Couldn't join — try again");
    } finally {
      setJoining(false);
    }
  }

  const target = preview?.team_name ? `${preview.workspace_name} / #${preview.team_name}` : preview?.workspace_name;

  return (
    <AuthLayout title="You're invited" subtitle={preview ? `${preview.invited_by_name} invited you to join` : "Loading invite…"}>
      <ErrorText>{loadError || joinError}</ErrorText>

      {preview && (
        <div className="mb-6 text-center">
          <p className="text-title font-semibold text-ink">{target}</p>
        </div>
      )}

      {preview && !preview.valid && (
        <p className="text-center text-body text-ink-dim">{preview.reason_invalid}</p>
      )}

      {preview?.valid && authLoading && <p className="text-center text-body text-ink-dim">Loading…</p>}

      {preview?.valid && !authLoading && !user && (
        <div className="flex flex-col gap-2.5">
          <Link to={`/signup?next=${encodeURIComponent(`/invite/${token}`)}`} className={`${primaryButtonClass} block text-center`}>
            Create an account to join
          </Link>
          <Link
            to={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}
            className="block text-center text-small text-ink-dim underline underline-offset-2 hover:text-ink"
          >
            Already have an account? Sign in
          </Link>
        </div>
      )}

      {preview?.valid && !authLoading && user && (
        <button onClick={handleJoin} disabled={joining} className={primaryButtonClass}>
          {joining ? "Joining…" : `Join as ${user.name}`}
        </button>
      )}
    </AuthLayout>
  );
}
