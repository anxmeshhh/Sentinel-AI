import { useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { SyncResult } from "../api/types";
import { Button, Icon } from "./ui";

type SyncState = "idle" | "syncing" | "success" | "error";

/**
 * "Sync Now" - triggers the real backend pipeline (POST /sync: provider pull
 * through the Intelligence Core, for the caller's own connections) and shows
 * exactly what it's doing, no more and no less.
 *
 * Three real states, driven by the request's own lifecycle - never a fake
 * percentage or a timer standing in for actual work. `idle` is disabled only
 * by nothing; `syncing` disables the button itself so a second click can't
 * queue a duplicate request while one is in flight. `success` is transient
 * (the backend is already done - this is a few seconds of "you can see it
 * happened" before the button goes quiet again), and a stale success timeout
 * from an earlier click can never stomp a sync that started after it, since
 * the revert only fires while state is still "success".
 *
 * `service` narrows a provider page's own Sync Now to just that service's
 * connections (POST /sync?service=gmail) - same endpoint, same pipeline, the
 * caller just isn't waiting on providers it didn't ask to sync. Omitted (the
 * Dashboard's usage), it syncs everything.
 */
export function SyncButton({ service, onSynced }: { service?: string; onSynced?: () => void }) {
  const [state, setState] = useState<SyncState>("idle");
  const [error, setError] = useState<string | null>(null);
  const revertTimer = useRef<number | undefined>(undefined);

  async function sync() {
    if (state === "syncing") return; // belt-and-suspenders - the button is disabled in this state anyway
    window.clearTimeout(revertTimer.current);
    setState("syncing");
    setError(null);
    try {
      const result = await api.post<SyncResult>(`/sync${service ? `?service=${encodeURIComponent(service)}` : ""}`);
      if (result.status === "failed") {
        setState("error");
        setError(result.errors[0] ?? "Sentinel couldn't reach your connected services.");
        return;
      }
      onSynced?.();
      setState("success");
      revertTimer.current = window.setTimeout(() => {
        setState((s) => (s === "success" ? "idle" : s));
      }, 2500);
    } catch (e) {
      setState("error");
      setError(e instanceof ApiError ? e.message : "Couldn't reach Sentinel - try again.");
    }
  }

  if (state === "error") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-caption text-crit">{error}</span>
        <Button size="sm" variant="secondary" onClick={() => void sync()}>
          <Icon name="refresh" size={13} /> Retry
        </Button>
      </div>
    );
  }

  return (
    <Button size="sm" variant="secondary" onClick={() => void sync()} disabled={state === "syncing"}>
      {state === "success" ? (
        <>
          <Icon name="check" size={13} className="text-good" />
          <span className="text-good">Synced just now</span>
        </>
      ) : (
        <>
          <Icon name="refresh" size={13} className={state === "syncing" ? "animate-spin" : undefined} />
          {state === "syncing" ? "Syncing…" : "Sync Now"}
        </>
      )}
    </Button>
  );
}
