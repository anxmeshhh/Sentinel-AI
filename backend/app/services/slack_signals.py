"""Slack's view of the shared conversation-signal vocabulary.

The logic that was here moved to services/conversation_signals.py when Teams
became the second chat provider - the lexicon and the system-message filter are
provider-agnostic, and duplicating them would guarantee they drift. What is
genuinely Slack-specific (its `<@U123>` mention grammar) still lives there too,
behind its own function, because there is no useful way to share a grammar.

This module stays as Slack's named entry point so the ingestion path and its
tests read in Slack's vocabulary and nothing about Slack behaviour changes.
"""

from app.services.conversation_signals import (  # noqa: F401  (re-exported API)
    LEXICON,
    SKIP_SUBTYPES,
    extract_slack_mentions as extract_mentions,
    match_lexicon,
)

__all__ = ["LEXICON", "SKIP_SUBTYPES", "extract_mentions", "match_lexicon"]
