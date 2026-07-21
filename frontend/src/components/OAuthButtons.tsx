import { useEffect, useState } from "react";

import { api } from "../api/client";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

interface Providers {
  google: boolean;
  microsoft: boolean;
}

/** Social sign-in options, shown only when they genuinely work.
 *
 * This used to render both buttons unconditionally under the hardcoded
 * line "Not configured yet in this environment" - which stayed on screen
 * long after Google credentials were added, telling users the working
 * button was broken. Google sign-in had consequently never once been
 * attempted against this backend. Availability now comes from the server
 * (GET /auth/providers) rather than being asserted in the markup.
 */
export function OAuthButtons() {
  const [providers, setProviders] = useState<Providers | null>(null);

  useEffect(() => {
    api
      .get<Providers>("/auth/providers")
      // If the check itself fails, show nothing rather than offering a
      // button that may not work - the same honesty in the other direction.
      .then(setProviders)
      .catch(() => setProviders({ google: false, microsoft: false }));
  }, []);

  if (!providers || (!providers.google && !providers.microsoft)) return null;

  return (
    <div className="mt-6">
      <div className="mb-4 flex items-center gap-3">
        <div className="h-px flex-1 bg-border" />
        <span className="text-caption text-ink-faint">or continue with</span>
        <div className="h-px flex-1 bg-border" />
      </div>
      <div className="flex flex-col gap-2.5">
        {providers.google && (
          <a
            href={`${API_BASE}/auth/google/login`}
            className="flex items-center justify-center gap-2.5 border border-border py-2.5 text-body font-medium text-ink transition-colors hover:border-ink"
          >
            <GoogleMark />
            Google
          </a>
        )}
        {providers.microsoft && (
          <a
            href={`${API_BASE}/auth/microsoft/login`}
            className="flex items-center justify-center gap-2.5 border border-border py-2.5 text-body font-medium text-ink transition-colors hover:border-ink"
          >
            <MicrosoftMark />
            Microsoft
          </a>
        )}
      </div>
      {/* Naming the boundary here heads off a real confusion: signing in
          with Google and connecting Gmail are separate OAuth flows with
          different scopes, and users reasonably assume one implies the other. */}
      <p className="mt-3 text-center text-caption text-ink-faint">
        Signing in with Google creates your account — it doesn't give Sentinel access to your email.
        You choose what to connect later.
      </p>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg width="15" height="15" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.49h4.84a4.14 4.14 0 0 1-1.8 2.71v2.26h2.9c1.7-1.57 2.7-3.88 2.7-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.8.54-1.83.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.95 10.7A5.4 5.4 0 0 1 3.67 9c0-.59.1-1.17.28-1.7V4.97H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.03l2.99-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.97l2.99 2.33C4.66 5.17 6.65 3.58 9 3.58z" />
    </svg>
  );
}

function MicrosoftMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}
