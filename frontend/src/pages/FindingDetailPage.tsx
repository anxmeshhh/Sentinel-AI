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
        <h1 className="text-h2 font-semibold text-balance">{finding.summary}</h1>
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

  return (
    <div className="rounded-md border border-border p-4">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-body">
        {Object.entries(evidence).map(([key, value]) => (
          <React.Fragment key={key}>
            <dt className="text-ink-faint">{key.replace(/_/g, " ")}</dt>
            <dd className="text-ink-dim">{JSON.stringify(value)}</dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
}
