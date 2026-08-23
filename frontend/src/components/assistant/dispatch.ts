import { api } from "../../api/client";
import type { AttentionItem, SentinelAction } from "../../api/types";

/**
 * The Assistant's one route to doing something.
 *
 * OBSERVE -> UNDERSTAND -> PLAN -> CONFIRM -> ACT -> VERIFY -> REPORT, with
 * the middle of that sentence owned entirely by the Action Registry. Nothing
 * here executes: it proposes a key that already exists in the registry with
 * parameters the registry then validates, and the server decides whether a
 * confirmation is required, whether the actor is authorized, what the risk
 * is, and whether the result verified.
 *
 * The reason this file exists at all is cost. `/actions/from-text` reads
 * intent out of prose and costs one LLM call; but when the Assistant already
 * knows the action key AND the target - because the item is on screen and the
 * verb was unambiguous - there is nothing left to interpret. `POST /actions`
 * has always accepted an explicit action_type and params. So the agentic path
 * for routine work is free, and the model is reached only for genuinely
 * ambiguous language.
 *
 * What this file must never become: a second execution layer. It has no
 * provider clients, no state writes and no risk logic of its own. Every
 * branch below ends in an Action Registry call.
 */

/** Where a proposal stands after `propose`. */
export type Proposed =
  | { kind: "needs_confirmation"; action: SentinelAction }
  | { kind: "ready"; action: SentinelAction };

/** Ask the registry for a proposal. Zero LLM: the key and params are known. */
export async function propose(
  actionType: string,
  params: Record<string, unknown>,
  opts?: { teamId?: string | null; reason?: string },
): Promise<Proposed> {
  const path = opts?.teamId ? `/teams/${opts.teamId}/actions` : "/actions";
  const action = await api.post<SentinelAction>(path, {
    action_type: actionType,
    params,
    reason: opts?.reason,
    source_kind: "assistant",
  });
  // The SERVER decides this, from the spec's risk and externality - the
  // client only reads it back. A LOW internal action arrives already
  // APPROVED; anything external or escalated arrives AWAITING_APPROVAL and
  // must be shown before it can run.
  return action.status === "approved"
    ? { kind: "ready", action }
    : { kind: "needs_confirmation", action };
}

/** Run an approved proposal. The registry executes, verifies and audits. */
export async function execute(action: SentinelAction): Promise<SentinelAction> {
  if (action.status === "awaiting_approval" || action.status === "proposed") {
    await api.post(`/actions/${action.id}/approve`);
  }
  return api.post<SentinelAction>(`/actions/${action.id}/execute`);
}

/**
 * What actually happened, in the user's words - built from the action row, so
 * it reports the registry's own verification rather than a hopeful sentence.
 * Zero LLM: this is string assembly over real fields.
 */
export interface Outcome {
  ok: boolean;
  headline: string;
  /** The registry's own `verification` string, when it produced one. */
  verification: string | null;
  /** True when it ran but could not be confirmed - not the same as failed. */
  uncertain: boolean;
}

export function describe(action: SentinelAction): Outcome {
  const what = (action.preview?.title as string) ?? action.action_type.replace(/_/g, " ");
  switch (action.status) {
    case "succeeded":
      return {
        ok: true,
        headline: `${what} — done and verified.`,
        verification: action.verification ?? null,
        uncertain: false,
      };
    case "unknown":
      // Deliberately not reported as success or failure: the change may
      // exist, so telling someone it failed invites a duplicate.
      return {
        ok: true,
        headline: `${what} — applied, but Sentinel couldn't confirm it.`,
        verification: action.verification ?? null,
        uncertain: true,
      };
    case "failed":
      return {
        ok: false,
        headline: action.error ?? `${what} — the provider refused that.`,
        verification: null,
        uncertain: false,
      };
    case "rejected":
    case "cancelled":
      return { ok: false, headline: "Cancelled — nothing was sent.", verification: null, uncertain: false };
    default:
      return { ok: false, headline: `${what} — ${action.status}.`, verification: null, uncertain: false };
  }
}

/* ------------------------------------------------------- target resolution */

export type Resolution<T> =
  | { kind: "none" }
  | { kind: "one"; item: T }
  | { kind: "many"; items: T[] };

/**
 * Which thing did they mean?
 *
 * Deterministic substring matching over what is already on screen - never a
 * model, because the answer is present in the conversation and asking a model
 * to re-derive it would be both slower and less accurate. Ambiguity is
 * resolved by ASKING, never by ranking: two candidates return `many` and the
 * caller shows a pick-list. A wrong action on the wrong item is not the kind
 * of mistake a confidence score should be allowed to make.
 */
export function resolveTarget<T>(
  subject: string | undefined,
  candidates: T[],
  textOf: (item: T) => string,
): Resolution<T> {
  if (candidates.length === 0) return { kind: "none" };

  // No subject at all ("mark this done") means the thing in focus. One
  // candidate is unambiguous; more than one still has to be asked about.
  if (!subject || !subject.trim()) {
    return candidates.length === 1 ? { kind: "one", item: candidates[0]! } : { kind: "many", items: candidates };
  }

  const q = subject.trim().toLowerCase();
  const matches = candidates.filter((c) => textOf(c).toLowerCase().includes(q));
  if (matches.length === 0) return { kind: "none" };
  if (matches.length === 1) return { kind: "one", item: matches[0]! };

  // An exact title match beats several partial ones - that is a fact about
  // the strings, not a guess about intent.
  const exact = matches.filter((c) => textOf(c).toLowerCase().trim() === q);
  if (exact.length === 1) return { kind: "one", item: exact[0]! };
  return { kind: "many", items: matches };
}

/** The searchable text of an attention item: its title and its reason. */
export function attentionText(item: AttentionItem): string {
  return `${item.title} ${item.why}`;
}

/* ------------------------------------------------------------ bulk selects */

/**
 * The named subsets a bulk request may refer to.
 *
 * Deliberately a small closed list rather than free-form filtering: "snooze
 * all low-priority items" has an unambiguous meaning, "snooze the ones that
 * don't matter" does not, and the second must not quietly become the first.
 * Priority comes from the attention engine's own score - nothing here decides
 * what low-priority means.
 */
export const BULK_SELECTORS: { key: string; label: string; pattern: RegExp; match: (i: AttentionItem) => boolean }[] = [
  {
    key: "low",
    label: "low-priority items",
    pattern: /\blow[- ]priority\b|\bunimportant\b/i,
    match: (i) => i.priority < 0.5,
  },
  {
    key: "detected",
    label: "findings Sentinel detected",
    pattern: /\b(these |all )?findings\b/i,
    match: (i) => i.origin === "detected",
  },
  {
    key: "all",
    label: "everything open",
    pattern: /\b(all|every|everything)\b/i,
    match: () => true,
  },
];

export function bulkSelectorFor(text: string) {
  return BULK_SELECTORS.find((s) => s.pattern.test(text));
}
