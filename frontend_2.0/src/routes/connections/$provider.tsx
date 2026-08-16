import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useState } from "react";

import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  EmptyState,
  InlineError,
  Panel,
  SectionLabel,
  SkeletonRows,
} from "@/components/sentinel/primitives";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/auth";
import {
  FAMILY_BLURB,
  FAMILY_LABEL,
  FAMILY_SERVICES,
  startConnect,
  type FamilyKey,
} from "@/lib/connect";
import { healthMeta, serviceByKey, type ServiceKey } from "@/lib/sentinel-data";
import { useConnections } from "@/lib/sentinel-live";

export const Route = createFileRoute("/connections/$provider")({
  head: () => ({ meta: [{ title: "Connection · Sentinel" }] }),
  component: ProviderDetail,
});

function ProviderDetail() {
  const { provider } = Route.useParams();
  const family = provider as FamilyKey;
  const router = useRouter();
  const { active } = useWorkspace();
  const { data, isLoading, isError, refetch } = useConnections();
  const [busy, setBusy] = useState<string | null>(null);

  const known = FAMILY_SERVICES[family];
  if (!known) {
    return (
      <div>
        <Back />
        <p className="t-small text-ink-dim">Sentinel doesn't know that provider.</p>
      </div>
    );
  }

  const mine = (data ?? []).filter((c) => known.includes(c.key));
  const account = mine[0]?.account;

  /** Services this family offers that are not present on this account. Named
   *  rather than hidden: "you don't have Teams" is information, not an error. */
  const missing = known.filter((k) => !mine.some((c) => c.key === k));

  async function disconnect(connectionId: string, name: string) {
    if (!window.confirm(`Disconnect ${name}? Sentinel will stop reading it and its findings will go.`))
      return;
    setBusy(connectionId);
    try {
      await api.delete(`/connections/${connectionId}`);
      await refetch();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-[80ch]">
      <Back />

      {isError ? (
        <InlineError message="Sentinel couldn't load this connection." onRetry={() => void refetch()} />
      ) : isLoading ? (
        <SkeletonRows rows={4} />
      ) : (
        <>
          <h1 className="t-h2 font-medium text-ink">{FAMILY_LABEL[family]}</h1>
          <p className="t-caption mt-1 text-ink-faint">
            {account ? `${account} · connected` : FAMILY_BLURB[family]}
          </p>

          {active && (
            <p className="t-caption mt-3 flex items-center gap-2 text-ink-faint">
              <Dot color={active.kind === "personal" ? "var(--ctx-personal)" : "var(--ctx-org)"} />
              {active.kind === "personal"
                ? "Connected in your Personal context. Only you can see this data."
                : `Shared in ${active.name}.`}
            </p>
          )}

          {mine.length === 0 ? (
            <div className="mt-6">
              <EmptyState
                title={`${FAMILY_LABEL[family]} isn't connected.`}
                body={FAMILY_BLURB[family]}
                action={
                  <ButtonSecondary onClick={() => void startConnect(family, `/connections/${family}`)}>
                    Connect {FAMILY_LABEL[family]}
                  </ButtonSecondary>
                }
              />
            </div>
          ) : (
            <>
              <section className="mt-8">
                <SectionLabel>Services</SectionLabel>
                <ul className="mt-3 divide-y divide-border border-y border-border">
                  {mine.map((s) => {
                    const h = healthMeta[s.health];
                    return (
                      <li key={s.connectionId} className="flex flex-wrap items-center gap-3 py-3">
                        <Dot color={h.color} />
                        <div className="min-w-0 flex-1">
                          <Link
                            to="/workspace/$service"
                            params={{ service: s.key }}
                            className="t-small block text-ink hover:underline"
                          >
                            {serviceByKey(s.key)?.name ?? s.name}
                          </Link>
                          <p className="t-caption text-ink-faint">
                            <span style={{ color: h.color }}>{h.word}</span>
                            {s.lastSynced !== "—" && ` · synced ${s.lastSynced}`}
                          </p>
                        </div>
                        <ButtonGhost
                          disabled={busy === s.connectionId}
                          onClick={() => void disconnect(s.connectionId, s.name)}
                        >
                          {busy === s.connectionId ? "…" : "Disconnect"}
                        </ButtonGhost>
                      </li>
                    );
                  })}
                </ul>
              </section>

              {missing.length > 0 && (
                <section className="mt-8">
                  <SectionLabel>Not available on this account</SectionLabel>
                  <ul className="mt-3 space-y-2">
                    {missing.map((k) => (
                      <li key={k}>
                        <Panel>
                          <p className="t-small text-ink">
                            🔒 {serviceByKey(k as ServiceKey)?.name ?? k}
                          </p>
                          <p className="t-caption mt-0.5 text-ink-faint">
                            {UNAVAILABLE[k] ??
                              "This service wasn't part of what you authorised. Reconnecting can add it."}
                          </p>
                        </Panel>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="mt-8">
                <SectionLabel>Permissions</SectionLabel>
                <p className="t-caption mt-2 text-ink-dim">
                  Sentinel reads metadata — titles, times, senders and status — and never stores
                  message bodies or file contents. Writes happen only when you confirm them, and
                  every one is recorded in{" "}
                  <Link to="/history" className="text-ink underline underline-offset-2">
                    History
                  </Link>
                  .
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <ButtonSecondary
                    onClick={() => void startConnect(family, `/connections/${family}`)}
                  >
                    Reconnect
                  </ButtonSecondary>
                  <ButtonGhost onClick={() => router.navigate({ to: "/connections" })}>
                    Back to connections
                  </ButtonGhost>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}

/** Why a service a family offers isn't here. Plan and account-type limits are
 *  facts about the account, so they are stated rather than shown as failures. */
const UNAVAILABLE: Record<string, string> = {
  microsoft_teams:
    "Requires a Microsoft 365 Business or work/school account. A personal Microsoft account doesn't include Teams.",
  google_drive: "Drive is searched live rather than synced, so it appears only when you search.",
};

function Back() {
  return (
    <Link to="/connections" className="t-caption mb-4 inline-block text-ink-faint hover:text-ink">
      ← Connections
    </Link>
  );
}
