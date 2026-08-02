"""Slack findings: deterministic detectors over ingested signals.

Phase 3. Every finding here is produced by a pure rule - no LLM - carries its
evidence, dedups, and auto-resolves when its condition disappears. The channel
classification (ResourcePriority) is load-bearing: a mention only matters in a
channel a person marked critical, exactly as a repo's silence only matters when
it is critical.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.security import encrypt_token
from app.models.attention_item import AttentionItem, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider, ResourcePriority
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services import attention_engine as ae

NOW = datetime.now(timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def env(session):
    ws = Workspace(name="Acme", slug=f"a-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="d@acme.test", name="D")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    return {"workspace": ws, "user": user}


def _channel(session, env, *, name="incidents", channel_id="C1", priority=ResourcePriority.NORMAL, paused=False):
    c = Connection(
        workspace_id=env["workspace"].id, user_id=env["user"].id, provider=Provider.SLACK,
        org="Acme", repo=channel_id, display_name=f"#{name}", github_login="T1",
        encrypted_token=encrypt_token("xoxb"), priority=priority,
        paused_at=NOW if paused else None,
    )
    session.add(c)
    session.commit()
    return c


def _sig(session, env, conn, sig_type, *, actor, minutes_ago=5, matched=None, mentions=None, ext=None):
    session.add(Signal(
        workspace_id=env["workspace"].id, connection_id=conn.id, type=sig_type,
        external_id=ext or f"{uuid.uuid4().hex[:10]}", actor=actor,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        payload={"snippet": "text", **({"matched": matched} if matched else {}), **({"mentions": mentions} if mentions else {})},
    ))
    session.commit()


# --- HIGH_PRIORITY_MENTION --------------------------------------------------


def test_mention_in_critical_channel_is_a_finding(session, env):
    ch = _channel(session, env, priority=ResourcePriority.CRITICAL)
    _sig(session, env, ch, SignalType.MENTION, actor="U1", mentions={"users": ["U9"]})
    [c] = ae._detect_slack_priority_mentions(session, env["workspace"].id, NOW)
    assert c["type"] == AttentionType.SLACK_MENTION
    assert c["evidence_url"].startswith("https://slack.com/app_redirect")
    assert "#incidents" in c["title"]


def test_mention_in_a_normal_channel_is_not_surfaced(session, env):
    """Slack already notifies plain mentions - only a critical channel makes one
    worth Sentinel's briefing."""
    ch = _channel(session, env, priority=ResourcePriority.NORMAL)
    _sig(session, env, ch, SignalType.MENTION, actor="U1", mentions={"users": ["U9"]})
    assert ae._detect_slack_priority_mentions(session, env["workspace"].id, NOW) == []


# --- BLOCKER_DISCUSSION -----------------------------------------------------


def test_flagged_blocker_is_a_finding(session, env):
    ch = _channel(session, env)
    _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["blocked"])
    [c] = ae._detect_slack_blockers(session, env["workspace"].id, NOW)
    assert c["type"] == AttentionType.SLACK_BLOCKER
    assert c["evidence_url"]


def test_urgent_but_not_a_blocker_is_not_a_blocker_finding(session, env):
    ch = _channel(session, env)
    _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["urgent"])  # no blocker term
    assert ae._detect_slack_blockers(session, env["workspace"].id, NOW) == []


# --- REPEATED_URGENT / ESCALATION_FORMING -----------------------------------


def test_repeated_urgent_signals_form_one_finding(session, env):
    ch = _channel(session, env)
    for _ in range(3):
        _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["urgent"])
    [c] = ae._detect_slack_urgent(session, env["workspace"].id, NOW)
    assert c["type"] == AttentionType.SLACK_URGENT
    assert "Repeated urgent" in c["title"]
    assert c["priority"] == 0.65


def test_a_multi_person_incident_forming_is_higher_severity(session, env):
    ch = _channel(session, env)
    _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["outage"])
    _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U2", matched=["incident"])
    [c] = ae._detect_slack_urgent(session, env["workspace"].id, NOW)
    assert "incident forming" in c["title"]
    assert c["priority"] == 0.85  # incident + 2 people outranks plain repetition


def test_urgent_below_threshold_is_not_a_finding(session, env):
    ch = _channel(session, env)
    _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["urgent"])  # only one, one person
    assert ae._detect_slack_urgent(session, env["workspace"].id, NOW) == []


def test_a_burst_is_one_finding_not_fifty(session, env):
    ch = _channel(session, env)
    for _ in range(20):
        _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["urgent"])
    found = ae._detect_slack_urgent(session, env["workspace"].id, NOW)
    assert len(found) == 1  # aggregated per channel


# --- lifecycle: dedup, auto-resolve, pause, evidence ------------------------


def test_findings_dedup_and_auto_resolve_through_refresh(session, env):
    ch = _channel(session, env, priority=ResourcePriority.CRITICAL)
    _sig(session, env, ch, SignalType.MENTION, actor="U1", mentions={"users": ["U9"]}, ext="m1")
    ae.refresh_attention(session, env["workspace"].id)
    items = session.execute(
        select(AttentionItem).where(AttentionItem.type == AttentionType.SLACK_MENTION)
    ).scalars().all()
    assert len(items) == 1 and items[0].state == AttentionState.NEW

    # Running again with the same signal must not create a second row (dedup).
    ae.refresh_attention(session, env["workspace"].id)
    assert session.execute(select(func.count()).where(AttentionItem.type == AttentionType.SLACK_MENTION)).scalar() == 1

    # The mention ages out of the window; the finding auto-resolves.
    session.query(Signal).filter(Signal.connection_id == ch.id).delete()
    session.commit()
    ae.refresh_attention(session, env["workspace"].id)
    assert session.get(AttentionItem, items[0].id).state == AttentionState.DONE


def test_paused_channel_produces_no_findings(session, env):
    ch = _channel(session, env, priority=ResourcePriority.CRITICAL, paused=True)
    _sig(session, env, ch, SignalType.MENTION, actor="U1", mentions={"users": ["U9"]})
    _sig(session, env, ch, SignalType.FLAGGED_MESSAGE, actor="U1", matched=["blocked"])
    assert ae._detect_slack_priority_mentions(session, env["workspace"].id, NOW) == []
    assert ae._detect_slack_blockers(session, env["workspace"].id, NOW) == []


# --- CRITICAL_CHANNEL_INACTIVE reuses the generic RESOURCE_STALLED ----------


def test_critical_channel_inactive_reuses_resource_stalled(session, env):
    """A critical channel gone silent is the generic 'critical resource stalled'
    situation - the same detector GitHub uses, no Slack-specific code."""
    from app.services.investigation import personal_scope
    from app.services.proactive import _detect_stalled_critical_resources
    from app.models.situation import ProactiveKind

    ch = _channel(session, env, name="deployment", priority=ResourcePriority.CRITICAL)
    # Its last activity was long ago - past the silence threshold.
    session.add(Signal(
        workspace_id=env["workspace"].id, connection_id=ch.id, type=SignalType.CHANNEL_ACTIVITY,
        external_id="old", actor="", occurred_at=NOW - timedelta(days=20), payload={"message_count": 3},
    ))
    session.commit()
    scope = personal_scope(session, env["workspace"].id, env["user"].id)
    [cand] = _detect_stalled_critical_resources(session, scope, [])
    assert cand.kind == ProactiveKind.RESOURCE_STALLED
    assert "#deployment" in cand.title
