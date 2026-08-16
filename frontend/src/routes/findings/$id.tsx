import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";

import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  InlineError,
  Panel,
  Pill,
  SectionLabel,
  SkeletonRows,
} from "@/components/sentinel/primitives";
import { api } from "@/lib/api";
import { serviceByKey, severityColor, severityLabel } from "@/lib/sentinel-data";
import { useFindings } from "@/lib/sentinel-live";

export const Route = createFileRoute("/findings/$id")({
  head: () => ({ meta: [{ title: "Finding · Sentinel" }] }),
  component: FindingDetail,
});

/**
 * Sourced from the attention list rather than a per-finding endpoint.
 *
 * `GET /findings/{id}` exists but serves the LEGACY agent findings, which are a
 * different thing from the canonical stream this page shows. The list is small
 * and already loaded, so selecting from it is both correct and cheaper than
 * adding an endpoint that would duplicate the same mapping.
 */
function FindingDetail() {
  const { id } = Route.useParams();
  const { data, isLoading, isError, refetch } = useFindings();
  const [busy, setBusy] = useState(false);

  const f = (data ?? []).find((row) => row.id === id);

  async function update(patch: Record<string, unknown>) {
    setBusy(true);
    try {
      await api.patch(`/attention/${id}`, patch);
      await refetch();
    } finally {
      setBusy(false);
    }
  }

  if (isError) {
    return <InlineError message="Sentinel couldn't load this finding." onRetry={() => void refetch()} />;
  }
  if (isLoading) return <SkeletonRows rows={5} />;
  if (!f) {
    return (
      <div>
        <Link to="/findings" className="t-caption mb-4 inline-block text-ink-faint hover:text-ink">
          ← Findings
        </Link>
        <p className="t-small text-ink-dim">
          That finding is no longer active — it was resolved, or the thing it described went away.
        </p>
      </div>
    );
  }

  const service = serviceByKey(f.service);

  return (
    <div className="max-w-[72ch]">
      <Link to="/findings" className="t-caption mb-4 inline-block text-ink-faint hover:text-ink">
        ← Findings
      </Link>

      <div className="flex flex-wrap items-center gap-2">
        <Dot color={severityColor[f.severity]} />
        <span className="t-micro uppercase tracking-[0.06em]" style={{ color: severityColor[f.severity] }}>
          {severityLabel[f.severity]}
        </span>
        <Pill>{f.status}</Pill>
      </div>

      <h1 className="t-h3 mt-1 font-medium text-ink">{f.title}</h1>
      <p className="t-body mt-2 text-ink-dim">{f.why}</p>

      <div className="mt-5 flex flex-wrap items-center gap-2 border-y border-border py-3">
        <ButtonSecondary disabled={busy} onClick={() => void update({ state: "done" })}>
          Mark done
        </ButtonSecondary>
        <ButtonGhost
          onClick={() =>
            void update({
              state: "snoozed",
              // The API takes an absolute instant, not a duration.
              snoozed_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
            })
          }
        >
          Snooze 24h
        </ButtonGhost>
        <ButtonGhost onClick={() => void update({ state: "dismissed" })}>Dismiss</ButtonGhost>
        {f.evidence[0]?.link && (
          <a
            href={f.evidence[0].link}
            target="_blank"
            rel="noreferrer"
            className="t-caption ml-auto text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Open in {service?.name ?? "provider"} ↗
          </a>
        )}
      </div>

      {f.evidence.length > 0 && (
        <section className="mt-6">
          <SectionLabel>Evidence</SectionLabel>
          <ul className="mt-2 space-y-2">
            {f.evidence.map((e, i) => (
              <li key={i}>
                <Panel>
                  <p className="t-small text-ink">{e.what}</p>
                  <p className="t-caption mt-0.5 text-ink-faint">{e.when}</p>
                  {e.link && (
                    <a
                      href={e.link}
                      target="_blank"
                      rel="noreferrer"
                      className="t-caption mt-1 inline-block text-ink-faint underline underline-offset-2 hover:text-ink"
                    >
                      Open ↗
                    </a>
                  )}
                </Panel>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-6">
        <SectionLabel>Source</SectionLabel>
        <p className="t-caption mt-2 text-ink-dim">
          {service?.name ?? "Sentinel"} · detected {f.when}
        </p>
      </section>

      {f.situationId && (
        <section className="mt-6">
          <SectionLabel>Situation</SectionLabel>
          <Link to="/situations/$id" params={{ id: f.situationId }} className="mt-2 block">
            <Panel className="transition-colors duration-150 hover:border-border-strong">
              <p className="t-small text-ink">Sentinel connected this with other findings.</p>
              <p className="t-caption mt-0.5 text-ink-faint">View the situation →</p>
            </Panel>
          </Link>
        </section>
      )}
    </div>
  );
}
