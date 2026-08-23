import type { SuggestionGroup } from "../SentinelPanel";

/**
 * Per-provider AI Assistant config, shared across every page for that
 * provider family - one Microsoft config used by Outlook Mail, Outlook
 * Calendar, To Do, OneDrive and OneNote alike, so five pages can never drift
 * into five slightly different assistants. Each is real: `endpointBase`
 * names an already-built, already-registered backend router
 * (/connections/{provider}/command/stream) - not a relabelled call to the
 * general Assistant. A provider with no such router (Slack, Zoom, Notion)
 * has no entry here and gets no AI panel, rather than a fake scoped one.
 */
export interface ProviderAssistantConfig {
  contextLabel: string;
  endpointBase: string;
  placeholder?: string;
  suggestions?: string[];
  suggestionGroups?: SuggestionGroup[];
}

export const GOOGLE_ASSISTANT: ProviderAssistantConfig = {
  contextLabel: "Google Workspace",
  endpointBase: "/connections/google",
  suggestions: [
    "What are my most important unread emails?",
    "What's on my calendar this week?",
    "Find my most recently edited Drive files",
  ],
};

export const MICROSOFT_ASSISTANT: ProviderAssistantConfig = {
  contextLabel: "Microsoft 365",
  endpointBase: "/connections/microsoft",
  placeholder: "Ask about your mail, calendar or channels…",
  // Every prompt here is audited against what Sentinel actually stores, so a
  // suggested prompt never lands on "I don't have that".
  suggestionGroups: [
    {
      label: "Mail",
      prompts: [
        "Which emails need my attention?",
        "Summarize my important unread emails.",
        "What arrived today?",
        "Which unread emails are addressed directly to me?",
        "Which conversations have the most back-and-forth?",
      ],
    },
    {
      label: "Calendar",
      prompts: [
        "What meetings should I prepare for?",
        "What's on my schedule today?",
        "Are there any overlapping meetings?",
        "Which meetings are most important?",
      ],
    },
    {
      label: "Channels",
      prompts: ["Which channels require attention?", "What's the status of my monitored channels?"],
    },
    {
      label: "Workspace",
      prompts: [
        "What requires my attention today?",
        "Summarize my workspace.",
        "What should I prioritize?",
        "Give me my briefing.",
      ],
    },
  ],
};

export const GITHUB_ASSISTANT: ProviderAssistantConfig = {
  contextLabel: "GitHub",
  endpointBase: "/connections/github",
  placeholder: "Ask about your repositories…",
  suggestionGroups: [
    {
      label: "Repository Health",
      prompts: [
        "Which repositories need my attention?",
        "Show me inactive repositories.",
        "Which repositories are at risk?",
      ],
    },
    {
      label: "Development",
      prompts: [
        "What changed this week?",
        "Summarize recent development activity.",
        "Which pull requests are waiting?",
        "Which issues need review?",
      ],
    },
    {
      label: "Insights",
      prompts: [
        "Which repositories should I prioritize?",
        "Compare activity across repositories.",
        "Give me a GitHub briefing.",
      ],
    },
  ],
};
