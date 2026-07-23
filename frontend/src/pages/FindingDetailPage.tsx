import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Finding } from "../api/types";
import { severityBand } from "../api/types";
import { BackNav } from "../components/BackNav";
import { SeverityChip } from "../components/SeverityChip";
import { LoadingBlock } from "../components/ui";

export function FindingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [finding, setFinding] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api
      .get<Finding>(`/findings/${id}`)
      .then(setFinding)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load finding"));
  }, [id]);

  if (error) return <p className="text-crit">{error}</p>;
  if (!finding) return <LoadingBlock />;

  const severity = severityBand(finding.severity);

  return (
    <div>
      <BackNav back={{ to: "/", label: "Today's Brief" }} crumbs={[{ label: "Dashboard", to: "/" }, { label: "Finding" }]} />
      <div className="mb-1 flex flex-wrap items-center gap-2.5">
        <SeverityChip severity={severity} />
        <h1 className="text-h2 font-medium text-balance">{finding.summary}</h1>
      </div>
      <p className="mb-6 text-body text-ink-dim">
        {finding.agent} agent · {Math.round(finding.confidence * 100)}% confidence
      </p>

      <SectionLabel>Root cause</SectionLabel>
      <p className="mb-6 max-w-2xl text-lead">{finding.root_cause}</p>

      <SectionLabel>Suggested action</SectionLabel>
      <div className="mb-6 flex max-w-2xl items-start gap-2.5 rounded-md border border-good bg-good/10 p-3.5">
        <span className="text-good">➜</span>
        <span>{finding.suggested_action}</span>
      </div>

      <SectionLabel>Evidence</SectionLabel>
      <EvidenceView evidence={finding.evidence} />
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="label-sub mb-2.5 mt-5 text-body font-bold text-ink-dim">
      {children}
    </div>
  );
}

function EvidenceView({ evidence }: { evidence: Record<string, unknown> }) {
  const pullRequests = evidence.pull_requests as Array<Record<string, unknown>> | undefined;

  if (Array.isArray(pullRequests) && pullRequests.length > 0) {
    return (
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse text-small">
          <thead>
            <tr>
              {Object.keys(pullRequests[0]).map((key) => (
                <th
                  key={key}
                  className="label-sub border-b border-border px-2.5 py-2 text-left"
                >
                  {key.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pullRequests.map((pr, i) => (
              <tr key={i}>
                {Object.entries(pr).map(([key, value]) => (
                  <td key={key} className="border-b border-border px-2.5 py-2 text-ink-dim last:border-b-0">
                    {key === "number" || key === "url" ? (
                      <a
                        href={String(pr.url ?? "#")}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent-text hover:underline"
                      >
                        #{String(pr.number ?? value)}
                      </a>
                    ) : Array.isArray(value) ? (
                      value.join(", ")
                    ) : (
                      String(value)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // Structured cards, not a wall of JSON. Each field is labelled and its
  // value formatted for a human; the raw payload stays available behind an
  // expander for anyone who actually needs it, rather than being the default
  // a normal reader has to decode.
  const entries = Object.entries(evidence).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="flex flex-col gap-2">
      {entries.map(([key, value]) => (
        <EvidenceField key={key} label={key.replace(/_/g, " ")} value={value} />
      ))}
      <details className="mt-1">
        <summary className="cursor-pointer text-caption text-ink-faint hover:text-ink-dim">View raw data</summary>
        <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-surface-2 p-3 text-micro text-ink-dim">
          {JSON.stringify(evidence, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function EvidenceField({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-border bg-surface p-3">
      <div className="label-sub mb-1 text-ink-faint">{label}</div>
      <div className="text-body text-ink-dim">{formatEvidenceValue(value)}</div>
    </div>
  );
}

function formatEvidenceValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) {
    if (value.length === 0) return "none";
    // Arrays of objects (e.g. related items) become compact rows; arrays of
    // scalars become a comma list.
    if (typeof value[0] === "object") {
      return (
        <div className="flex flex-col gap-1">
          {value.map((item, i) => (
            <div key={i} className="text-small">
              {Object.entries(item as Record<string, unknown>)
                .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`)
                .join(" · ")}
            </div>
          ))}
        </div>
      );
    }
    return value.map(String).join(", ");
  }
  if (typeof value === "object") {
    return (
      <div className="flex flex-col gap-0.5">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k} className="text-small">
            <span className="text-ink-faint">{k.replace(/_/g, " ")}: </span>
            {String(v)}
          </div>
        ))}
      </div>
    );
  }
  // A URL becomes a link; an ISO timestamp becomes a readable date.
  const str = String(value);
  if (/^https?:\/\//.test(str)) {
    return <a href={str} target="_blank" rel="noreferrer" className="text-accent-text hover:underline">{str}</a>;
  }
  if (/^\d{4}-\d{2}-\d{2}T/.test(str)) return new Date(str).toLocaleString();
  return str;
}
