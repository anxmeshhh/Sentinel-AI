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
  | "situations" // "what's going on"                 -> /situations
  | "investigate" // "what's happening with X"         -> entity-scoped lookup
  | "memory" // "what do you remember"             -> /memory
  | "search" // "find everything about X"          -> across what Sentinel holds
  | "ask"; // anything else                      -> grounded chat

export interface Classified {
  intent: Intent;
  /** The thing the question is about, for investigate/search. */
  subject?: string;
}

const RULES: { intent: Intent; patterns: RegExp[] }[] = [
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
      /\bwhat (needs|requires) my attention\b/i,
      /\b(anything|what'?s) urgent\b/i,
      /\bwhat should i (deal with|do|handle|tackle) (first|now)\b/i,
      /\bwhat matters\b/i,
      /\bmy (attention|priorit)/i,
    ],
  },
  {
    intent: "memory",
    patterns: [/\bwhat do you remember\b/i, /\byour memor/i, /\bpatterns?\b.*\bseen\b/i],
  },
  {
    intent: "situations",
    patterns: [/\bsituations?\b/i, /\bwhat'?s going on\b/i, /\bwhat'?s developing\b/i],
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

export function classify(text: string): Classified {
  const trimmed = text.trim();
  for (const rule of RULES) {
    if (rule.patterns.some((p) => p.test(trimmed))) {
      const subject = subjectOf(trimmed);
      return subject ? { intent: rule.intent, subject } : { intent: rule.intent };
    }
  }
  const subject = subjectOf(trimmed);
  return subject ? { intent: "ask", subject } : { intent: "ask" };
}

/** The starter questions. Deliberately phrased the way the router recognises
 *  them, so the suggestions and the parser can never drift apart. */
export const SUGGESTIONS = [
  "What did I miss?",
  "What's urgent?",
  "Prepare me for my next meeting",
  "What do you remember?",
] as const;
