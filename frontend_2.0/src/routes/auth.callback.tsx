import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/auth/callback")({
  component: OAuthCallback,
});

/**
 * Where Google/Microsoft sign-in lands.
 *
 * The token arrives in the URL FRAGMENT, not the query string - a fragment is
 * never sent to a server or written to server logs, which is the point. That
 * also means this can only ever run on the client.
 */
function OAuthCallback() {
  const { loginWithToken } = useAuth();
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) {
      setFailed(true);
      return;
    }
    loginWithToken(token)
      .then(() => router.navigate({ to: "/", replace: true }))
      .catch(() => setFailed(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (failed) router.navigate({ to: "/login", replace: true });
  }, [failed, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="t-body text-ink-dim">Signing you in…</p>
    </div>
  );
}
