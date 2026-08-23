/**
 * What is the user asking for?
 *
 * The Assistant is a conversation layer over the Intelligence Core, not a
 * second brain. So this file does exactly one thing: decide which EXISTING
 * capability answers a message. It never decides what matters, never ranks
 * anything, and never produces a finding - it picks an endpoint.
 *
 * The matching is deterministic keyword matching rather than an LLM call, for
 * three reasons: it is instant, it is inspectable (you can read why a message
 * routed where it did), and it cannot hallucinate an intent. Anything it does
 * not confidently recognise falls through to ASK, which is the existing
 * grounded /assistant/chat endpoint - so the failure mode is "answered as a
 * question" rather than "did something unexpected".
 *
 * Order matters: the first pattern that matches wins, and the list is ordered
 * most-specific first. ACTION sits above everything because "schedule a
 * meeting about what I missed" is a request to act, not a request to recap.
 */
export type Intent =
  | "action" // "schedule…", "create…", "draft…"  -> Action Registry proposal
  | "remember" // "remember that…"                  -> Memory (see the gap below)
  | "prepare" // "prepare me for my meeting"       -> Context Engine / prepare
  | "catchup" // "what did I miss"                 -> /attention/catchup
  | "attention" // "what's urgent"                   -> /attention, ranked
  | "findings" // "what did you detect"             -> /attention, origin=detected
  | "situations" // "what's going on"                 -> /situations
  | "goals" // "am I on track"                     -> /goals, computed health
  | "decisions" // "what do you recommend"           -> /decisions, proposed
  | "status" // "what are you watching"            -> /attention/status
  | "investigate" // "what's happening with X"         -> entity-scoped lookup
  | "memory" // "what do you remember"             -> /memory
  | "search" // "find everything about X"          -> across what Sentinel holds
  | "provider" // "anything from GitHub?"            -> Core data, filtered
  | "resolve" // "mark this done" / "snooze this"   -> Action Registry, 0 LLM
  | "ask"; // anything else                      -> grounded chat

export interface Classified {
  intent: Intent;
  /** The thing the question is about, for investigate/search. */
  subject?: string;
  /** A provider id the question named, if any - "anything from GitHub?".
   *  Narrows the answer to Core data from that provider. It is a FILTER over
   *  what Sentinel has already analysed, never a live query: the provider AI
   *  panels own live provider access and keep it. */
  provider?: string;
}

/** Words people actually type -> the provider id the Core stores.
 *
 *  Derived from the same provider vocabulary the rest of the UI uses
 *  (PROVIDER_LABEL in components/situations.ts); the aliases exist because
 *  nobody types "microsoft_outlook_calendar". Deliberately NOT a fuzzy match -
 *  an unrecognised word means no provider was named, not a guess. */
const PROVIDER_ALIASES: { id: string; patterns: RegExp[] }[] = [
  { id: "github", patterns: [/\bgithub\b/i, /\bgit hub\b/i, /\bprs?\b/i, /\bpull requests?\b/i] },
  { id: "slack", patterns: [/\bslack\b/i] },
  { id: "zoom", patterns: [/\bzoom\b/i] },
  { id: "gmail", patterns: [/\bgmail\b/i] },
  { id: "google_calendar", patterns: [/\bgoogle calendar\b/i] },
  { id: "google_drive", patterns: [/\b(google )?drive\b/i] },
  { id: "microsoft_outlook_mail", patterns: [/\boutlook mail\b/i] },
  { id: "microsoft_outlook_calendar", patterns: [/\boutlook calendar\b/i] },
  { id: "microsoft_todo", patterns: [/\b(microsoft )?to ?do\b/i] },
  { id: "microsoft_onedrive", patterns: [/\bonedrive\b/i] },
  { id: "microsoft_onenote", patterns: [/\bonenote\b/i] },
  { id: "microsoft_teams", patterns: [/\b(microsoft )?teams\b/i] },
  // Generic words, checked last so "outlook calendar" wins over "calendar".
  { id: "outlook", patterns: [/\boutlook\b/i] },
  { id: "calendar", patterns: [/\bcalendar\b/i] },
  { id: "mail", patterns: [/\b(e-?mail|inbox)\b/i] },
];

/** Which lifecycle change "mark this done" is asking for.
 *
 *  Deterministic, and it maps onto the three Action Registry keys rather than
 *  onto free text - `attention.done`, `attention.dismiss`, `attention.snooze`.
 *  Snooze also carries a duration, read from the same words people actually
 *  use; anything unrecognised defaults to tomorrow rather than guessing wide. */
export interface ResolveRequest {
  state: "done" | "dismissed" | "snoozed";
  /** Hours, for snooze only. */
  hours?: number;
}

const SNOOZE_DURATIONS: { hours: number; pattern: RegExp }[] = [
  { hours: 3, pattern: /\b(a few hours|3 hours|this afternoon|later today)\b/i },
  { hours: 24, pattern: /\b(tomorrow|a day|24 hours)\b/i },
  { hours: 24 * 7, pattern: /\b(next week|a week|7 days)\b/i },
];

export function resolveRequestOf(text: string): ResolveRequest {
  if (/\bdismiss|hide|ignore\b/i.test(text)) return { state: "dismissed" };
  if (/\bsnooze|remind me|later|tomorrow|next week\b/i.test(text)) {
    const match = SNOOZE_DURATIONS.find((d) => d.pattern.test(text));
    return { state: "snoozed", hours: match?.hours ?? 24 };
  }
  return { state: "done" };
}

/** The provider named in the text, or undefined. First match wins, and the
 *  list is ordered specific-before-generic for exactly that reason. */
export function providerOf(text: string): string | undefined {
  for (const entry of PROVIDER_ALIASES) {
    if (entry.patterns.some((p) => p.test(text))) return entry.id;
  }
  return undefined;
}

const RULES: { intent: Intent; patterns: RegExp[] }[] = [
  {
    // Resolving something already on screen. Above `action` because "mark
    // this done" is a request to act on a KNOWN target, and a known target
    // needs no model to interpret: the item id comes from the conversation,
    // the action key is fixed, and the Action Registry does the rest. This is
    // the difference between an agent that operates the product and a chatbot
    // that describes it - and it costs nothing to run.
    intent: "resolve",
    patterns: [
      /\b(mark|set)\b.*\b(as )?(done|complete|completed|resolved|handled)\b/i,
      /\b(done|handled|sorted|resolved) (with )?(this|that|it)\b/i,
      /^(done|dismiss|snooze)\b/i,
      /\bdismiss (this|that|it)\b/i,
      /\b(hide|ignore) (this|that|it)\b/i,
      /\bsnooze (this|that|it)\b/i,
      /\bremind me (about )?(this|that|it) (later|tomorrow|next week)\b/i,
    ],
  },
  {
    intent: "action",
    patterns: [
      /\b(schedule|set up|book)\b.*\b(meeting|call|event|time)\b/i,
      /\b(create|add|make)\b.*\b(task|todo|to-do|reminder|goal|commitment)\b/i,
      /\b(draft|write|compose)\b.*\b(email|reply|message|note)\b/i,
      /\b(remind me)\b/i,
    ],
  },
  {
    intent: "remember",
    patterns: [/\bremember (that|this|to)\b/i, /\bdon'?t let me forget\b/i, /\bi always want\b/i],
  },
  {
    intent: "prepare",
    patterns: [/\bprepare me\b/i, /\bprep me\b/i, /\bwhat should i know before\b/i, /\bbrief me\b/i],
  },
  {
    intent: "catchup",
    patterns: [
      /\bwhat did i miss\b/i,
      /\bcatch me up\b/i,
      /\bwhat (happened|changed)\b/i,
      /\bwhile i was (away|out|gone)\b/i,
    ],
  },
  {
    intent: "attention",
    patterns: [
      /\bwhat (needs|requires|wants) my attention\b/i,
      /\b(anything|what'?s|is anything) urgent\b/i,
      /\bwhat should i (deal with|do|look at|handle|tackle|work on|focus on) (first|now|today|next)\b/i,
      /\bwhat matters\b/i,
      /\bmy (attention|priorit)/i,
      /\b(show|list|any)\b.*\b(open|outstanding|pending)\b.*\b(items?|things?|work)\b/i,
      /\bwhat'?s (on my plate|pending|outstanding|open)\b/i,
      /\bneeds? (me|doing|action)\b/i,
    ],
  },
  {
    intent: "memory",
    patterns: [
      /\bwhat do you remember\b/i,
      /\byour memor/i,
      /\bpatterns?\b.*\b(seen|learned|noticed)\b/i,
      /\bwhat have you learn(ed|t)\b/i,
      /\bwhat keeps (happening|recurring)\b/i,
    ],
  },
  {
    intent: "situations",
    patterns: [
      /\bsituations?\b/i,
      /\bwhat'?s going on\b/i,
      /\bwhat'?s developing\b/i,
      /\bwhat'?s (brewing|unfolding)\b/i,
      // Bare "what's happening" only. The lookahead hands "what's happening
      // WITH X" to `investigate` below, which is a question about one thing
      // rather than a request for the whole list.
      /\bwhat'?s happening\b(?!\s+(?:with|on|to)\b)/i,
    ],
  },
  {
    // Findings = what Sentinel DETECTED, as opposed to what you wrote down.
    // The distinction the Findings page is built on, recognised here so the
    // question is answered from data already loaded rather than by the model.
    intent: "findings",
    patterns: [
      /\bfindings?\b/i,
      /\bwhat (did|have) you (detect|find|found|pick(ed)? up|spot(ted)?)\b/i,
      /\bwhat (issues?|problems?|risks?) (did|have) you\b/i,
      /\banything (wrong|broken|concerning)\b/i,
    ],
  },
  {
    intent: "goals",
    patterns: [
      // Anchored rather than a bare /goals?/ - "the goal of this meeting" is
      // not a request to list Goals, and a greedy pattern here would swallow
      // it before the router reached a better-fitting intent.
      /^goals?\??$/i,
      /\b(my|our)\s+goals?\b/i,
      /\b(show|list)\b.*\bgoals?\b/i,
      /\bgoals?\b.*\b(status|health|progress|on track)\b/i,
      /\b(am i|are we) on track\b/i,
      /\bhow (am i|are we) doing\b/i,
      /\bwhat (am i|are we) working (towards?|toward)\b/i,
    ],
  },
  {
    intent: "decisions",
    patterns: [
      /\bwhat do you (recommend|suggest|advise)\b/i,
      /\bwhat (should|would) you do\b/i,
      /\byour recommendations?\b/i,
      /\bany (suggestions?|recommendations?)\b/i,
    ],
  },
  {
    // "Is Sentinel actually working?" - answered from the status the Core
    // already publishes, never by asking a model to describe itself.
    intent: "status",
    patterns: [
      /\bwhat (are you|is sentinel) (watching|monitoring|tracking)\b/i,
      /\bwhat'?s connected\b/i,
      /\b(are you|is everything) (working|ok|okay|healthy|synced|up to date)\b/i,
      /\b(sentinel|system) status\b/i,
      /\bhow many (signals?|providers?|services?)\b/i,
      /\bwhen did (you|it) last sync\b/i,
    ],
  },
  {
    intent: "search",
    patterns: [/\bfind (everything|anything|all)\b/i, /\bsearch for\b/i, /\bshow me everything\b/i],
  },
  {
    intent: "investigate",
    patterns: [
      /\bwhat'?s happening (with|on|to)\b/i,
      /\bwhat'?s the (status|state) of\b/i,
      /\btell me about\b/i,
      /\bwhy are you telling me\b/i,
      /\bwhere did (this|that) come from\b/i,
    ],
  },
];

/** Pulls the thing being asked about out of the sentence, so "what's happening
 *  with heartbeat-harmony" can be matched against real entity names. Returns
 *  undefined rather than guessing when there is no clear subject. */
function subjectOf(text: string): string | undefined {
  const m =
    /\b(?:happening (?:with|on|to)|status of|state of|tell me about|everything (?:about|on)|search for|updates? on|related to)\s+(.+)$/i.exec(
      text,
    );
  if (!m) return undefined;
  return m[1]
    .replace(/[?.!,]+$/, "")
    .replace(/\b(please|for me|thanks)\b/gi, "")
    .trim()
    .slice(0, 80) || undefined;
}

/**
 * Intent + subject + provider, all deterministically.
 *
 * Scope is deliberately NOT returned here. It is chosen explicitly in the
 * Assistant's scope chip and never inferred from wording: a mis-parsed
 * "for the team" that silently answered about the wrong scope would be the
 * one kind of wrongness this product cannot afford, and the server would
 * still be enforcing permissions underneath a confusing answer.
 */
export function classify(text: string): Classified {
  const trimmed = text.trim();
  const provider = providerOf(trimmed);
  for (const rule of RULES) {
    if (rule.patterns.some((p) => p.test(trimmed))) {
      return { intent: rule.intent, subject: subjectOf(trimmed), provider };
    }
  }
  // No rule matched, but a provider was named ("anything from GitHub?",
  // "any Slack blockers?"). That is answerable from what the Core has already
  // analysed for that provider, so it goes to the deterministic provider view
  // rather than spending a call asking a model to paraphrase the same rows.
  if (provider) return { intent: "provider", subject: subjectOf(trimmed), provider };
  return { intent: "ask", subject: subjectOf(trimmed), provider };
}

/** The starter questions. Deliberately phrased the way the router recognises
 *  them, so the suggestions and the parser can never drift apart. Every one
 *  of these routes to a deterministic intent - the opening screen therefore
 *  never suggests a question that costs an LLM call to answer. */
export const SUGGESTIONS = [
  "What did I miss?",
  "What's urgent?",
  "What's happening?",
  "Prepare me for my next meeting",
] as const;

/** The fuller set for the opening screen, where there is room to teach more
 *  of the vocabulary. Same rule as SUGGESTIONS: every one routes to a
 *  deterministic intent. */
export const QUICK_ASKS = [
  "What did I miss?",
  "What's urgent?",
  "What's happening?",
  "What did you detect?",
  "Am I on track?",
  "What do you recommend?",
  "Prepare me for my next meeting",
  "What do you remember?",
] as const;

/**
 * The LLM budget for one Assistant request, per intent.
 *
 * This is the structural form of the rule "a normal Assistant request makes
 * at most ONE model call". Every intent declares its ceiling here, the router
 * is exhaustive over `Intent` (so a new intent cannot be added without
 * choosing a budget), and the Assistant asserts against it at runtime. The
 * rule is therefore enforced by the type system and a check, not by everyone
 * remembering it.
 *
 * 0 means the answer comes entirely from data the Core already computed.
 * 1 means exactly one call, and never a chain: no intent may call the model,
 * read the result, and call it again.
 */
export const LLM_BUDGET: Record<Intent, 0 | 1> = {
  // Answered from `useIntelligence` state that is already in memory.
  attention: 0,
  findings: 0,
  situations: 0,
  goals: 0,
  decisions: 0,
  status: 0,
  memory: 0,
  investigate: 0, // matched against already-correlated situations/findings
  search: 0, // same - Sentinel searches what it has analysed, not providers
  remember: 0, // an honest "I can't store that yet" notice
  // Core data filtered to one provider. Deliberately NOT a proxy to that
  // provider's own AI panel: the orchestrator behind those panels is
  // multi-step by design (MAX_STEPS = 10) and wrapping it here would quietly
  // break this table's promise. Live provider questions get a link instead.
  provider: 0,
  // Acting on a target already on screen. The action key is fixed and the id
  // comes from the conversation, so nothing needs interpreting - it goes
  // straight to the Action Registry, which still validates, authorizes,
  // executes, verifies and audits exactly as it would for any other caller.
  resolve: 0,

  // One call each, server-side, and each already change-gated or cached.
  catchup: 1, // /attention/catchup narrates the delta (only past a 12h gap)
  prepare: 1, // meeting_prep, cached per event by get_cached_brief
  action: 1, // action_intent turns text into ONE registry proposal
  ask: 1, // the grounded fallback, over deterministic Core context
};

/** True when answering this intent cannot reach the model at all. */
export function isDeterministic(intent: Intent): boolean {
  return LLM_BUDGET[intent] === 0;
}
