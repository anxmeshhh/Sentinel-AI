import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelKnowledge } from "../../api/types";
import { EmptyState, Icon, LoadingBlock } from "../ui";

/** The authorized documents this channel can reference - Drive files on the
 *  channel's allow-list. Fail-closed: a Drive connection assigned with no
 *  allow-listed files yields no knowledge, correctly. */
export function KnowledgeModule({ teamId }: { teamId: string }) {
  const [data, setData] = useState<ChannelKnowledge | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<ChannelKnowledge>(`/teams/${teamId}/knowledge`));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock />;
  if (!data || data.no_connections) {
    return (
      <EmptyState
        title="No knowledge yet"
        description="Knowledge is the documents this channel is authorized to reference. Assign a Drive connection and allow-list specific files in Extensions, and they'll appear here."
      />
    );
  }
  if (data.documents.length === 0) {
    return (
      <EmptyState
        title="No documents authorized"
        description="A Drive connection is assigned, but no specific files are allow-listed for this channel yet. An admin authorizes them in Extensions — nothing is exposed by default."
      />
    );
  }

  return (
    <div>
      <p className="mb-4 text-caption text-ink-faint">
        {data.documents.length} authorized document{data.documents.length === 1 ? "" : "s"} this channel can reference.
      </p>
      <div className="rule-rows border-t border-rule">
        {data.documents.map((doc) => (
          <a
            key={doc.id}
            href={doc.url ?? undefined}
            target="_blank"
            rel="noreferrer"
            className="group flex items-center gap-3 rule-cell-interactive"
          >
            <Icon name="file" size={16} className="flex-none text-ink-faint" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-small text-ink group-hover:underline">{doc.title}</div>
              <div className="truncate text-micro text-ink-faint">
                {doc.owner ? `${doc.owner} · ` : ""}
                {new Date(doc.modified_at).toLocaleDateString()} · {doc.source_label}
              </div>
            </div>
            {doc.url && <Icon name="external" size={13} className="flex-none text-ink-faint" />}
          </a>
        ))}
      </div>
    </div>
  );
}
