"""Microsoft Teams (Sprint 2) - metadata, deterministic signals, and the two
claims that matter most:

  * Teams reuses the SHARED conversation detectors - it added no detection logic
    of its own, so a Teams blocker becomes a finding through the same code path
    a Slack blocker does.
  * Cross-provider correlation needs NO Microsoft-specific logic: a Teams channel
    is just a CHANNEL entity, so the Intelligence Core correlates a Teams blocker
    with a GitHub PR exactly as it already correlated Slack with GitHub.

Plus the honest one: when the tenant has not granted the protected message
permission, monitoring degrades to metadata rather than failing or inventing
activity.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.integrations.graph_client import GraphClient
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider, ResourcePriority
from app.models.entity import Entity, EntityKind
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.providers.workspace_grants import MICROSOFT_GRANT
from app.repositories.signals import SignalRepository
from app.services.attention_engine import refresh_attention
from app.services.conversation_signals import extract_teams_mentions, match_lexicon, strip_html
from app.services.entity_engine import extract_entities
from app.services.findings import list_findings
from app.services.grants import provision_grant
from app.services.investigation import personal_scope
from app.services.situation_engine import correlate
from app.services.teams_connections import add_channel, monitored_channels

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
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="u@acme.test", name="U")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    return {"ws": ws, "user": user, "_s": session}


# ------------------------------------------------- Phase 1: grant + metadata

def test_microsoft_grant_provisions_a_teams_anchor(session, env):
    """Teams is an anchor on the grant: connecting Microsoft 365 records the
    account and shares the token, but chooses no channels - those are picked."""
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="u@contoso.com", encrypted_token="tok")
    rows = session.execute(select(Connection).where(Connection.provider == Provider.MICROSOFT_TEAMS)).scalars().all()
    assert len(rows) == 1
    anchor = rows[0]
    assert anchor.repo == ""  # an anchor, not a monitored channel
    assert anchor.encrypted_token == "tok"
    assert monitored_channels(session, env["ws"].id, env["user"].id) == []


def test_adding_a_channel_creates_a_monitored_resource(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="u@contoso.com", encrypted_token="tok")
    ch = add_channel(session, workspace_id=env["ws"].id, user_id=env["user"].id,
                     team_id="T1", team_name="Platform", channel_id="C1", channel_name="deploys")
    assert ch.org == "T1"          # the team id, needed for every Graph call
    assert ch.repo == "C1"         # the channel id, stable across renames
    assert ch.display_name == "Platform / deploys"
    assert len(monitored_channels(session, env["ws"].id, env["user"].id)) == 1


def test_reconnect_refreshes_the_token_on_every_teams_row(session, env):
    """Every monitored channel shares the one grant token, so a reconnect must
    refresh them ALL - not just the first row found. Two channels on purpose:
    the first claims the empty anchor (the documented provider_account
    behaviour, shared with Slack and GitHub), the second is a row of its own, so
    this genuinely exercises the multi-row path."""
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="u@contoso.com", encrypted_token="tok1")
    add_channel(session, workspace_id=env["ws"].id, user_id=env["user"].id,
                team_id="T1", team_name="Platform", channel_id="C1", channel_name="deploys")
    add_channel(session, workspace_id=env["ws"].id, user_id=env["user"].id,
                team_id="T1", team_name="Platform", channel_id="C2", channel_name="incidents")

    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="u@contoso.com", encrypted_token="tok2")
    rows = session.execute(select(Connection).where(Connection.provider == Provider.MICROSOFT_TEAMS)).scalars().all()
    assert {r.repo for r in rows} == {"C1", "C2"}  # both kept, none duplicated
    assert {r.encrypted_token for r in rows} == {"tok2"}  # every row refreshed


def test_switching_microsoft_account_clears_the_previous_channels(session, env):
    """A different Microsoft account is a different world: its predecessor's
    monitored channels must not linger against a token that can no longer read
    them. Handled by the shared provider_account path, verified here for Teams."""
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="old@contoso.com", encrypted_token="tok1")
    add_channel(session, workspace_id=env["ws"].id, user_id=env["user"].id,
                team_id="T1", team_name="Platform", channel_id="C1", channel_name="deploys")

    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="new@contoso.com", encrypted_token="tok2")
    assert monitored_channels(session, env["ws"].id, env["user"].id) == []  # old channels gone
    rows = session.execute(select(Connection).where(Connection.provider == Provider.MICROSOFT_TEAMS)).scalars().all()
    assert len(rows) == 1 and rows[0].repo == ""  # a fresh anchor for the new account


# --------------------------------------------- Phase 2: deterministic signals

def _graph(monkeypatch, items):
    client = GraphClient("fake-token")
    monkeypatch.setattr(client, "_paginate", lambda path, params, cap: items)
    return client


def test_teams_mentions_prefer_the_structured_array(monkeypatch):
    mentions = [{"mentioned": {"user": {"id": "u-1", "displayName": "Jane"}}},
                {"mentioned": {"conversation": {"displayName": "General"}}}]
    got = extract_teams_mentions('<at id="0">Jane</at> please look', mentions)
    assert got == {"users": ["u-1"], "groups": ["General"]}


def test_teams_mentions_fall_back_to_the_html_body(monkeypatch):
    got = extract_teams_mentions('<p><at id="0">Jane Doe</at> ping</p>', [])
    assert got == {"users": ["Jane Doe"], "groups": []}
    assert extract_teams_mentions("<p>no mentions here</p>", []) is None


def test_operational_lexicon_is_shared_and_covers_teams_vocabulary():
    """One lexicon for every chat provider - and it covers the deploy/rollback
    vocabulary the Teams sprint named."""
    assert match_lexicon("We are blocked waiting for approval on the deploy") == ["approval", "blocked", "deploy"]
    assert match_lexicon("rollback needed, this is a sev1 incident") == ["incident", "rollback", "sev1"]
    assert match_lexicon("all good, shipping today") == []


def test_strip_html_makes_teams_bodies_readable():
    assert strip_html("<p>We&#39;re <b>blocked</b> &amp; waiting</p>").replace("  ", " ") == "We're blocked & waiting"


def test_channel_messages_degrade_when_the_protected_permission_is_missing(monkeypatch):
    """A 403 on messages is a normal tenant configuration, not a failure: the
    client reports it as (no messages, not allowed) so monitoring degrades."""
    import httpx

    client = GraphClient("fake-token")

    def _forbidden(path, params, cap):
        resp = httpx.Response(403, request=httpx.Request("GET", "https://graph.microsoft.com/x"))
        raise httpx.HTTPStatusError("forbidden", request=resp.request, response=resp)

    monkeypatch.setattr(client, "_paginate", _forbidden)
    messages, allowed = client.channel_messages("T1", "C1", NOW - timedelta(days=1))
    assert messages == [] and allowed is False


def test_channel_messages_normalize_and_respect_the_since_window(monkeypatch):
    raw = [
        {"id": "m1", "createdDateTime": "2026-08-07T10:00:00.0000000Z",
         "from": {"user": {"id": "u-1", "displayName": "Jane"}},
         "body": {"content": "<p>We are <b>blocked</b> on approval</p>"},
         "mentions": [], "importance": "high", "messageType": "message", "webUrl": "https://teams/m1"},
        {"id": "old", "createdDateTime": "2020-01-01T10:00:00Z", "from": {"user": {}},
         "body": {"content": "ancient"}, "mentions": [], "messageType": "message"},
    ]
    msgs, allowed = _graph(monkeypatch, raw).channel_messages("T1", "C1", datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert allowed is True
    assert [m["id"] for m in msgs] == ["m1"]  # the pre-window message is dropped
    assert msgs[0]["importance"] == "high" and msgs[0]["url"] == "https://teams/m1"


# ------------------ the claim: Teams reuses the SHARED detectors, unchanged ---

def _teams_channel(env, *, priority=ResourcePriority.NORMAL):
    s = env["_s"]
    conn = Connection(workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.MICROSOFT_TEAMS,
                      org="T1", repo="C1", display_name="Platform / deploys",
                      encrypted_token="x", last_synced_at=NOW, priority=priority)
    s.add(conn)
    s.flush()
    return conn


def test_a_teams_blocker_becomes_a_finding_through_the_shared_detector(session, env):
    """No Teams-specific detector exists: this is the same code that turns a
    Slack blocker into a finding."""
    conn = _teams_channel(env)
    SignalRepository(session, env["ws"].id).upsert(
        connection_id=conn.id, type=SignalType.FLAGGED_MESSAGE, external_id="m1", actor="u-1",
        occurred_at=NOW - timedelta(hours=2),
        payload={"matched": ["blocked", "approval"], "snippet": "We are blocked on approval",
                 "actor_name": "Jane", "url": "https://teams/m1"},
    )
    session.commit()

    refresh_attention(session, env["ws"].id)
    items = session.execute(
        select(AttentionItem).where(AttentionItem.type == AttentionType.CONVERSATION_BLOCKER)
    ).scalars().all()
    assert len(items) == 1
    item = items[0]
    assert item.source_provider == "microsoft_teams"      # honest provenance
    assert item.dedupe_key.startswith("microsoft_teams_blocker:")  # own namespace, no Slack collision
    assert item.evidence_url == "https://teams/m1"         # Teams' own deep link


def test_teams_mention_requires_a_critical_channel_like_slack(session, env):
    """The same rule as Slack: only mentions in channels a person marked CRITICAL
    become findings, so Sentinel never just re-notifies what Teams already did."""
    normal = _teams_channel(env)
    repo = SignalRepository(session, env["ws"].id)
    repo.upsert(connection_id=normal.id, type=SignalType.MENTION, external_id="m1", actor="u-1",
                occurred_at=NOW - timedelta(hours=1),
                payload={"mentions": {"users": ["u-2"], "groups": []}, "snippet": "ping"})
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert session.execute(select(AttentionItem).where(AttentionItem.type == AttentionType.CONVERSATION_MENTION)).scalars().all() == []

    normal.priority = ResourcePriority.CRITICAL
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert len(session.execute(select(AttentionItem).where(AttentionItem.type == AttentionType.CONVERSATION_MENTION)).scalars().all()) == 1


# --------- the claim: correlation needs NO Microsoft-specific logic ----------

def test_teams_channel_resolves_to_a_channel_entity(session, env):
    conn = _teams_channel(env)
    session.add(AttentionItem(
        workspace_id=env["ws"].id, type=AttentionType.CONVERSATION_BLOCKER, origin=AttentionOrigin.DETECTED,
        state=AttentionState.NEW, source_provider="microsoft_teams", connection_id=conn.id,
        dedupe_key="k1", title="blocked", why="w", priority=0.8,
    ))
    session.commit()

    scope = personal_scope(session, env["ws"].id, env["user"].id)
    extract_entities(session, scope, list_findings(session, scope))
    ent = session.execute(select(Entity).where(Entity.kind == EntityKind.CHANNEL)).scalar_one()
    assert ent.key == "msteams:C1"
    assert ent.display_name == "Platform / deploys"


def test_teams_and_github_correlate_into_one_cross_provider_situation(session, env):
    """The Sprint 2 thesis, end to end: a Teams blocker naming a repository and a
    stalled PR on that repository become ONE situation - produced by the frozen
    Intelligence Core, which knows nothing about Microsoft."""
    s = env["_s"]
    gh = Connection(workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.GITHUB,
                    org="acme", repo="payments", encrypted_token="x", last_synced_at=NOW)
    s.add(gh)
    teams = _teams_channel(env)
    s.flush()
    s.add_all([
        AttentionItem(workspace_id=env["ws"].id, type=AttentionType.STALE_PR, origin=AttentionOrigin.DETECTED,
                      state=AttentionState.NEW, source_provider="github", connection_id=gh.id,
                      dedupe_key="k-pr", title="stale PR", why="awaiting review", priority=0.9),
        AttentionItem(workspace_id=env["ws"].id, type=AttentionType.CONVERSATION_BLOCKER, origin=AttentionOrigin.DETECTED,
                      state=AttentionState.NEW, source_provider="microsoft_teams", connection_id=teams.id,
                      dedupe_key="k-blk", title="blocked on the payments deploy", why="waiting on approval",
                      priority=0.85),
    ])
    s.commit()

    scope = personal_scope(s, env["ws"].id, env["user"].id)
    findings = list_findings(s, scope)
    extract_entities(s, scope, findings)
    situations = correlate(s, scope, findings)

    repo_entity = session.execute(select(Entity).where(Entity.kind == EntityKind.REPO)).scalar_one()
    sit = next(x for x in situations if x.primary_entity_id == repo_entity.id)
    assert sit.member_count == 2
    assert sit.cross_provider is True
    assert sit.provider_count == 2
    # The title names the providers the way a person does. It used to read
    # "repo: 2 related findings across github, microsoft_teams" - a database
    # row read aloud - and this asserts the raw ids stay out of it.
    assert "GitHub" in sit.title and "Microsoft Teams" in sit.title
    assert "microsoft_teams" not in sit.title
