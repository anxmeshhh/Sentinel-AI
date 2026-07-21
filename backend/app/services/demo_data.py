"""Phase 2r: the seeded "Explore Sentinel" workspace.

Lets someone experience the full product - Catch Me Up, Attention, and real
cross-service AI investigation - without connecting a real Google/GitHub
account. This matters for demos, expos, and anyone evaluating Sentinel who
(reasonably) won't hand over OAuth access to their actual inbox.

Two design rules make this honest rather than a puppet show:

1. **Demo data goes through the same pipeline as real data.** Fake Gmail /
   Calendar / Drive / GitHub facts are written as ordinary `Signal` rows,
   then the *real* attention engine detects over them. Nothing about the
   attention list is scripted - if a detector is wrong, the demo shows it
   being wrong, which is exactly what you want from a demo.

2. **The AI genuinely reasons.** The orchestrator runs its real
   tool-calling loop; only the tool *implementations* read seeded Signals
   instead of calling a provider API (see orchestrator's demo branches).
   The model is not fed canned answers.

The scenario is deliberately one that covers both launch audiences at once
(startup/developer AND busy professional): a founder with a client demo in
a few hours, a contract question waiting, an invoice due, and a stale PR.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_token
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.attention_engine import refresh_attention

logger = structlog.get_logger("sentinel.demo")

DEMO_ACCOUNT = "you@brightloop.io"
DEMO_REPO_ORG = "brightloop"
DEMO_REPO_NAME = "payments-service"


def _placeholder_token() -> str:
    """Demo connections must never hold real credentials. This is a valid
    *shape* (so any accidental decrypt doesn't explode) that is useless as
    an actual token - every demo code path is expected to short-circuit
    before a provider call is ever attempted."""
    return encrypt_token(json.dumps({"access_token": "demo", "refresh_token": "demo", "expires_at": "2099-01-01T00:00:00+00:00"}))


def get_demo_workspace(session: Session, user: User) -> Workspace | None:
    return session.execute(
        select(Workspace)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id, Workspace.is_demo.is_(True))
    ).scalars().first()


def create_demo_workspace(session: Session, user: User) -> tuple[Workspace, int]:
    """Idempotent: re-entering Explore mode re-seeds the same workspace with
    fresh relative timestamps rather than piling up new ones. Returns the
    workspace and how many signals were seeded."""
    workspace = get_demo_workspace(session, user)
    if workspace is None:
        workspace = Workspace(
            name="Explore Sentinel",
            slug=f"demo-{uuid.uuid4().hex[:12]}",
            kind=WorkspaceKind.ORGANIZATION,  # so Groups/Channels surfaces are reachable in the demo
            is_demo=True,
        )
        session.add(workspace)
        session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))
        session.commit()

    return workspace, seed_demo_signals(session, workspace, user.id)


def seed_demo_signals(session: Session, workspace: Workspace, user_id: uuid.UUID) -> int:
    """Wipe and re-seed. Timestamps are relative to *now* every time, so a
    demo given today reads as "3 hours from now", not a stale fixed date -
    the single biggest thing that makes seeded data feel dead."""
    now = datetime.now(timezone.utc)

    connections = _ensure_demo_connections(session, workspace, user_id)
    session.query(Signal).filter(Signal.workspace_id == workspace.id).delete()
    session.flush()

    rows = (
        _demo_emails(workspace, connections[Provider.GMAIL], now)
        + _demo_events(workspace, connections[Provider.GOOGLE_CALENDAR], now)
        + _demo_drive_files(workspace, connections[Provider.GOOGLE_DRIVE], now)
        + _demo_prs(workspace, connections[Provider.GITHUB], now)
    )
    for row in rows:
        session.add(row)
    session.commit()

    # Real detectors over seeded facts - the attention list is genuinely
    # computed, never scripted.
    refresh_attention(session, workspace.id)
    logger.info("demo_workspace_seeded", workspace_id=str(workspace.id), signals=len(rows))
    return len(rows)


def _ensure_demo_connections(session: Session, workspace: Workspace, user_id: uuid.UUID) -> dict[Provider, Connection]:
    wanted = {
        Provider.GMAIL: (DEMO_ACCOUNT, "gmail"),
        Provider.GOOGLE_CALENDAR: (DEMO_ACCOUNT, "calendar"),
        Provider.GOOGLE_DRIVE: (DEMO_ACCOUNT, "drive"),
        Provider.GITHUB: (DEMO_REPO_ORG, DEMO_REPO_NAME),
    }
    result: dict[Provider, Connection] = {}
    for provider, (org, repo) in wanted.items():
        existing = session.execute(
            select(Connection).where(Connection.workspace_id == workspace.id, Connection.user_id == user_id, Connection.provider == provider)
        ).scalars().first()
        if existing is None:
            existing = Connection(
                workspace_id=workspace.id, user_id=user_id, provider=provider, org=org, repo=repo,
                encrypted_token=_placeholder_token(), last_synced_at=datetime.now(timezone.utc),
            )
            session.add(existing)
            session.flush()
        result[provider] = existing
    session.commit()
    return result


def _signal(workspace, connection, *, type_, external_id, actor, payload, occurred_at) -> Signal:
    return Signal(
        workspace_id=workspace.id, connection_id=connection.id, type=type_,
        external_id=external_id, actor=actor, payload=payload, occurred_at=occurred_at,
    )


def _demo_emails(workspace, connection, now) -> list[Signal]:
    # `body` is demo-only: real Gmail bodies are never stored (see
    # gmail_client.py) - here it stands in for the live fetch so the AI can
    # actually read a message in demo mode.
    spec = [
        (
            "demo-mail-1", "Contract question before Thursday's demo",
            "Priya Raman <priya@acmecorp.com>", ["UNREAD", "STARRED", "IMPORTANT", "INBOX"], 1,
            "Hi,\n\nAhead of the demo, our legal team flagged one item in the proposal: clause 7.2 "
            "on data retention. Can you confirm whether customer data is deleted within 30 days of "
            "contract termination, and whether that's contractually guaranteed?\n\nWe'd like this "
            "settled before we present internally on Thursday.\n\nThanks,\nPriya",
        ),
        (
            "demo-mail-2", "Investor update — numbers for the September memo",
            "Daniel Osei <daniel@northpeak.vc> ", ["UNREAD", "IMPORTANT", "INBOX"], 2,
            "Hey,\n\nPutting together the LP memo this week. Could you send Q3 ARR, net retention, "
            "and current runway by Friday? Rough numbers are fine, I'll mark them as unaudited.\n\nDaniel",
        ),
        (
            "demo-mail-3", "Invoice INV-2291 is due in 3 days",
            "billing@cloudhost.com", ["UNREAD", "IMPORTANT", "INBOX"], 3,
            "Invoice INV-2291 for $842.00 covering September infrastructure is due in 3 days. "
            "Auto-payment is not enabled on this account.",
        ),
        (
            "demo-mail-4", "Re: roadmap doc — added Q4 section",
            "Sam Whitfield <sam@brightloop.io>", ["INBOX"], 1,  # read: correctly NOT attention-worthy
            "Added the Q4 section to the roadmap doc. Take a look when you get a chance, no rush.",
        ),
        (
            "demo-mail-5", "50% off developer tools this week only!",
            "deals@toolsweekly.com", ["UNREAD", "IMPORTANT", "CATEGORY_PROMOTIONS"], 1,  # promo: must be filtered out
            "Our biggest sale of the year on developer tooling.",
        ),
    ]
    return [
        _signal(
            workspace, connection, type_=SignalType.EMAIL, external_id=ext_id, actor=sender,
            payload={
                "subject": subject, "from": sender, "to": DEMO_ACCOUNT,
                "label_ids": labels, "thread_id": f"thread-{ext_id}", "body": body,
            },
            occurred_at=now - timedelta(days=age_days, hours=2),
        )
        for ext_id, subject, sender, labels, age_days, body in spec
    ]


def _demo_events(workspace, connection, now) -> list[Signal]:
    demo_start = now + timedelta(hours=3)
    planning_start = now + timedelta(days=1, hours=2)
    retro_start = now - timedelta(days=2)
    spec = [
        (
            "demo-evt-1", "Product Demo — Acme Corp", demo_start, demo_start + timedelta(minutes=45),
            ["priya@acmecorp.com", "raj@acmecorp.com", "sam@brightloop.io"], True,
        ),
        (
            "demo-evt-2", "Sprint Planning", planning_start, planning_start + timedelta(hours=1),
            ["sam@brightloop.io", "mia@brightloop.io"], True,
        ),
        (
            "demo-evt-3", "Design Review (last week)", retro_start, retro_start + timedelta(minutes=30),
            ["mia@brightloop.io"], True,
        ),
    ]
    return [
        _signal(
            workspace, connection, type_=SignalType.CALENDAR_EVENT, external_id=ext_id, actor=DEMO_ACCOUNT,
            payload={
                "title": title, "start": start.isoformat(), "end": end.isoformat(), "status": "confirmed",
                "organizer": DEMO_ACCOUNT, "attendee_emails": attendees, "attendee_count": len(attendees),
                "has_meeting_link": has_meet,
                "meet_url": f"https://meet.google.com/demo-{ext_id}" if has_meet else None,
                "url": f"https://calendar.google.com/calendar/event?eid={ext_id}",
            },
            occurred_at=start,
        )
        for ext_id, title, start, end, attendees, has_meet in spec
    ]


def _demo_drive_files(workspace, connection, now) -> list[Signal]:
    spec = [
        (
            "demo-doc-1", "Acme Corp — Proposal v3", "application/vnd.google-apps.document", 1,
            "ACME CORP — PLATFORM PROPOSAL (v3)\n\n"
            "Scope: Sentinel deployment across Acme's support and operations teams (120 seats).\n\n"
            "Pricing: $18/seat/month, annual commitment, 15% first-year discount.\n\n"
            "Clause 7.2 — Data retention: customer data is permanently deleted within 30 days of "
            "contract termination. This is contractually guaranteed and independently audited "
            "annually.\n\n"
            "Timeline: pilot begins 2 weeks after signature; full rollout within 6 weeks.\n\n"
            "Open items: legal review of clause 7.2, security questionnaire, SSO requirements.",
        ),
        (
            "demo-doc-2", "Q3 Roadmap", "application/vnd.google-apps.document", 4,
            "Q3 ROADMAP\n\nShipped: payment retries, audit log, SSO (beta).\n"
            "In progress: usage-based billing, admin analytics.\n"
            "Q4 (draft): mobile app, webhooks, SOC 2 Type II readiness.\n"
            "Deadline: SOC 2 evidence collection must be complete by 30 November.",
        ),
        (
            "demo-doc-3", "Demo Script — Acme", "application/vnd.google-apps.document", 0,
            "DEMO SCRIPT — ACME\n\n1. Problem framing (3 min): scattered tools, missed follow-ups.\n"
            "2. Attention feed walkthrough (7 min) — lead with their own use case: support escalations.\n"
            "3. Cross-tool investigation (5 min).\n4. Security & permissions (5 min) — expect clause 7.2 questions.\n"
            "5. Pricing and next steps (5 min).",
        ),
        (
            "demo-doc-4", "Q3 Metrics", "application/vnd.google-apps.spreadsheet", 6,
            "Metric,Value\nARR,$1.24M\nNet retention,112%\nRunway (months),19\nLogo churn,2.1%",
        ),
    ]
    return [
        _signal(
            workspace, connection, type_=SignalType.DRIVE_FILE, external_id=ext_id, actor=DEMO_ACCOUNT,
            payload={
                "name": name, "mime_type": mime, "content": content,
                "url": f"https://docs.google.com/document/d/{ext_id}/edit",
                "owner": "You", "shared": ext_id == "demo-doc-1",
            },
            occurred_at=now - timedelta(days=age_days, hours=5),
        )
        for ext_id, name, mime, age_days, content in spec
    ]


def _demo_prs(workspace, connection, now) -> list[Signal]:
    spec = [
        ("demo-pr-482", "Add payment retry logic for failed charges", "mia", 6, None),
        ("demo-pr-479", "Fix timezone handling in invoice scheduler", "sam", 9, None),
        ("demo-pr-475", "Upgrade dependencies", "mia", 12, now - timedelta(days=10)),  # merged: not stale
    ]
    return [
        _signal(
            workspace, connection, type_=SignalType.PR, external_id=ext_id, actor=author,
            payload={
                "title": title, "number": int(ext_id.split("-")[-1]), "author": author,
                "url": f"https://github.com/{DEMO_REPO_ORG}/{DEMO_REPO_NAME}/pull/{ext_id.split('-')[-1]}",
                "merged_at": merged_at.isoformat() if merged_at else None,
                "base_branch": "main", "additions": 120, "deletions": 30, "changed_files": 4,
                "changed_dirs": ["payments"],
            },
            occurred_at=now - timedelta(days=age_days),
        )
        for ext_id, title, author, age_days, merged_at in spec
    ]
