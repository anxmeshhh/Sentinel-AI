"""Structured Gmail browsing - the whole point is to avoid an open-ended
query engine (IA principle from the Google module plan: a small fixed set of
views, not a freeform system). Every filter here is a plain, predictable
query over already-ingested metadata; nothing here calls the LLM.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.signal import Signal
from app.repositories.signals import SignalRepository

NOISE_LABELS = ["SPAM", "TRASH"]

MAIL_CATEGORY_LABELS = {
    "primary": "CATEGORY_PERSONAL",
    "social": "CATEGORY_SOCIAL",
    "promotions": "CATEGORY_PROMOTIONS",
    "updates": "CATEGORY_UPDATES",
    "forums": "CATEGORY_FORUMS",
}

MAIL_FILTERS = {"recent", "starred", "important", "spam", "unread", "category", "top"}

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "what", "did", "do", "does", "email", "mail",
    "message", "say", "said", "about", "from", "to", "in", "on", "of", "my", "that", "this",
    "recent", "latest", "last", "show", "me", "list", "it", "out", "for", "with", "and", "has",
}


def list_mail(session: Session, workspace_id, *, mail_filter: str, category: str | None = None, limit: int = 30) -> list[Signal]:
    repo = SignalRepository(session, workspace_id)

    if mail_filter == "recent":
        return repo.list_mail(exclude_labels=NOISE_LABELS, limit=limit)
    if mail_filter == "starred":
        return repo.list_mail(labels_any=["STARRED"], limit=limit)
    if mail_filter == "important":
        return repo.list_mail(labels_any=["IMPORTANT"], limit=limit)
    if mail_filter == "spam":
        return repo.list_mail(labels_any=["SPAM"], limit=limit)
    if mail_filter == "unread":
        return repo.list_mail(labels_any=["UNREAD"], exclude_labels=NOISE_LABELS, limit=limit)
    if mail_filter == "category":
        label = MAIL_CATEGORY_LABELS.get((category or "").lower())
        if label is None:
            raise ValueError(f"unknown mail category: {category!r}")
        return repo.list_mail(labels_any=[label], exclude_labels=NOISE_LABELS, limit=limit)
    if mail_filter == "top":
        return _list_top(repo, limit)

    raise ValueError(f"unknown mail filter: {mail_filter!r}")


def _list_top(repo: SignalRepository, limit: int) -> list[Signal]:
    """Top N = important/starred first, topped up with plain recency if that's not enough."""
    flagged = repo.list_mail(labels_any=["IMPORTANT", "STARRED"], exclude_labels=NOISE_LABELS, limit=limit)
    if len(flagged) >= limit:
        return flagged[:limit]

    seen_ids = {s.id for s in flagged}
    fill = repo.list_mail(exclude_labels=NOISE_LABELS, limit=limit + len(flagged))
    result = list(flagged)
    for s in fill:
        if len(result) >= limit:
            break
        if s.id not in seen_ids:
            result.append(s)
            seen_ids.add(s.id)
    return result


def match_mail_intent(question: str) -> tuple[str, str | None] | None:
    """Maps a short natural-language phrase to one of MAIL_FILTERS - a rule-based
    matcher, not an LLM call, so results stay predictable and free.
    """
    q = question.lower()

    for key, label in MAIL_CATEGORY_LABELS.items():
        if key in q or label.replace("CATEGORY_", "").lower() in q:
            return "category", key

    if "top" in q:
        return "top", None
    if "spam" in q or "junk" in q:
        return "spam", None
    if "star" in q:
        return "starred", None
    if "important" in q:
        return "important", None
    if "unread" in q:
        return "unread", None
    if "recent" in q or "latest" in q or "new" in q:
        return "recent", None

    return None


def mail_summary_for_assistant(session: Session, workspace_id, limit: int = 5) -> str:
    repo = SignalRepository(session, workspace_id)
    recent = repo.list_mail(exclude_labels=NOISE_LABELS, limit=limit)
    starred = repo.list_mail(labels_any=["STARRED"], limit=limit)
    spam_count = repo.count_mail(labels_any=["SPAM"])

    lines = ["Recent emails:" if recent else "No recent emails."]
    lines += [_render_line(s) for s in recent]
    lines.append("")
    lines.append("Starred emails:" if starred else "No starred emails.")
    lines += [_render_line(s) for s in starred]
    lines.append("")
    lines.append(f"Spam folder: {spam_count} message(s).")
    return "\n".join(lines)


def find_best_matching_email(session: Session, workspace_id, question: str) -> Signal | None:
    """Bounded keyword-overlap match against recent mail, used only to decide
    whether a chat question is specific enough to warrant a live body fetch
    (see assistant.py). Not a search engine - a small, honest heuristic.
    """
    words = {w.strip(".,?!\"'").lower() for w in question.split()}
    words = {w for w in words if len(w) >= 3 and w not in STOPWORDS}
    if not words:
        return None

    repo = SignalRepository(session, workspace_id)
    candidates = repo.list_mail(exclude_labels=NOISE_LABELS, limit=100)

    best, best_score = None, 0
    for s in candidates:
        haystack = f"{s.payload.get('subject', '')} {s.payload.get('from', '')}".lower()
        score = sum(1 for w in words if w in haystack)
        if score > best_score:
            best, best_score = s, score

    return best if best_score >= 1 else None


def _render_line(s: Signal) -> str:
    return f"- \"{s.payload.get('subject', '(no subject)')}\" from {s.payload.get('from', 'unknown')} ({s.occurred_at.isoformat()})"


GMAIL_LABEL_FILTERS = {
    "starred": "is:starred",
    "important": "is:important",
    "unread": "is:unread",
    "spam": "is:spam",
}


def build_gmail_query(
    *,
    keywords: str | None = None,
    sender: str | None = None,
    label_filter: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> str:
    """Translates structured search intent (what the AI Command orchestrator's
    search_emails tool extracts from a natural-language request) into a real
    Gmail search query string - used by GmailClient.search() for a live,
    whole-mailbox search via Gmail's own index, not a local filter.
    """
    parts: list[str] = []
    if keywords:
        parts.append(keywords)
    if sender:
        parts.append(f"from:{sender}")
    if label_filter and label_filter in GMAIL_LABEL_FILTERS:
        parts.append(GMAIL_LABEL_FILTERS[label_filter])
    if since:
        parts.append(f"after:{_to_gmail_date(since)}")
    if until:
        parts.append(f"before:{_to_gmail_date(until)}")
    return " ".join(parts) if parts else "in:inbox OR in:spam"


def _to_gmail_date(iso_date: str) -> str:
    try:
        return datetime.fromisoformat(iso_date[:10]).strftime("%Y/%m/%d")
    except ValueError:
        return iso_date
