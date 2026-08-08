"""The Outlook workspace: writes through the Action Registry, and the generic
service-intelligence endpoint the shell renders.

The properties worth protecting:
  * Every Microsoft write is an allow-listed action - confirm-first, verified
    against Microsoft's own state, and undoable.
  * Drafting and sending are different promises: a draft is reversible, while
    sending is HIGH risk, irreversible, confirmed every time, and offers no
    undo button - because none could work.
  * The intelligence endpoint is provider-AGNOSTIC - it filters the canonical
    Finding stream by service, so every future workspace page reuses it.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.action_registry import REGISTRY, validate_params

NOW = datetime.now(timezone.utc)
OUTLOOK_ACTIONS = ("outlook.mark_read", "outlook.flag", "outlook.draft", "outlook.reply_draft")


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
    mail = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.MICROSOFT_OUTLOOK_MAIL,
                      org="u@contoso.com", repo="mail", encrypted_token="x", last_synced_at=NOW)
    session.add(mail)
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "mail": mail, "_s": session}


# ------------------------------------------------- the safety boundary

@pytest.mark.parametrize("key", OUTLOOK_ACTIONS)
def test_every_outlook_write_is_external_confirm_first_and_undoable(key):
    spec = REGISTRY[key]
    assert spec.external is True                      # reaches the real mailbox
    assert spec.needs_approval is True                # therefore always confirmed
    assert spec.compensate is not None                # and undoable
    assert spec.verify is not None                    # and verified after the fact
    assert spec.available is True


def test_drafting_and_sending_are_different_promises():
    """Drafting and sending are deliberately NOT the same action. A draft is
    reversible and says it sends nothing; sending is a separate, high-risk,
    irreversible action a person must confirm on its own."""
    draft = REGISTRY["outlook.draft"]
    draft_preview = draft.preview(
        validate_params(draft, {"to": ["a@b.com"], "subject": "Hi", "body": "Hello"})
    )
    assert draft_preview["sends"] is False
    assert draft.reversibility.value == "reversible" and draft.compensate is not None

    send = REGISTRY["outlook.send"]
    assert send.risk.value == "high" and send.reversibility.value == "irreversible"

    # The generic (provider-neutral) email.send stays unavailable: it has no
    # implementation behind it, and an action that cannot work must say so.
    assert REGISTRY["email.send"].available is False


def test_parameters_are_validated_before_anything_runs():
    spec = REGISTRY["outlook.draft"]
    with pytest.raises(Exception):
        validate_params(spec, {"to": ["not-an-email"], "subject": "x", "body": "y"})
    with pytest.raises(Exception):
        validate_params(spec, {"to": [], "subject": "x", "body": "y"})
    ok = validate_params(spec, {"to": ["a@b.com"], "subject": "x", "body": "y"})
    assert ok.to == ["a@b.com"]


def test_previews_describe_the_real_effect():
    read = REGISTRY["outlook.mark_read"]
    p = read.preview(validate_params(read, {"message_id": "m1", "is_read": True, "subject": "Deploy"}))
    assert "Mark as read" in p["summary"] and "Deploy" in p["summary"]
    p2 = read.preview(validate_params(read, {"message_id": "m1", "is_read": False, "subject": "Deploy"}))
    assert "Mark as unread" in p2["summary"]


def test_write_requires_a_connection_in_the_actions_own_scope(session, env):
    """The mailbox is resolved from the action's scope, never the caller - so a
    scope with no Outlook connection cannot write to anyone's mailbox."""
    from app.services.action_registry import ActionUnavailable, _outlook_connection

    class _Action:
        workspace_id = env["ws"].id
        scope_key = f"personal:{uuid.uuid4()}"  # a different person
        params: dict = {}

    assert _outlook_connection(session, _Action()) is None

    class _Mine(_Action):
        scope_key = f"personal:{env['user'].id}"

    assert _outlook_connection(session, _Mine()) is not None


def test_no_route_writes_to_graph_directly():
    """Structural guarantee: the workspace read router must not import a Graph
    write path other than the live body fetch, so the Action Registry stays the
    only way anything changes."""
    import app.api.routes.workspace as mod

    source = open(mod.__file__, encoding="utf-8").read()
    for forbidden in ("set_message_read", "set_message_flag", "create_draft", "create_reply_draft", "delete_message"):
        assert forbidden not in source, f"{forbidden} must only be reachable from the Action Registry"


# ------------------------------------------- generic intelligence endpoint

def test_service_intelligence_is_filtered_by_service(session, env):
    """A GitHub finding must never appear on the Outlook rail, and the endpoint
    itself contains no provider-specific reasoning."""
    from app.api.routes.workspace import service_intelligence

    gh = Connection(workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.GITHUB,
                    org="acme", repo="payments", encrypted_token="x", last_synced_at=NOW)
    session.add(gh)
    session.flush()
    session.add_all([
        AttentionItem(workspace_id=env["ws"].id, type=AttentionType.IMPORTANT_EMAIL,
                      origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
                      source_provider="microsoft_outlook_mail", connection_id=env["mail"].id,
                      dedupe_key="k1", title="Deploy approval needed", why="unread + important", priority=0.9),
        AttentionItem(workspace_id=env["ws"].id, type=AttentionType.STALE_PR,
                      origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
                      source_provider="github", connection_id=gh.id,
                      dedupe_key="k2", title="stale PR", why="awaiting review", priority=0.9),
    ])
    session.commit()

    out = service_intelligence(service="microsoft_mail", session=session,
                               workspace_id=env["ws"].id, user=env["user"])
    assert [f["title"] for f in out["findings"]] == ["Deploy approval needed"]
    assert out["critical_count"] == 1
    assert out["connected"] is True and out["account"] == "u@contoso.com"

    gh_out = service_intelligence(service="github", session=session,
                                  workspace_id=env["ws"].id, user=env["user"])
    assert [f["title"] for f in gh_out["findings"]] == ["stale PR"]


def test_unknown_service_is_rejected(session, env):
    from fastapi import HTTPException

    from app.api.routes.workspace import service_intelligence

    with pytest.raises(HTTPException) as exc:
        service_intelligence(service="not_a_service", session=session,
                             workspace_id=env["ws"].id, user=env["user"])
    assert exc.value.status_code == 404


def test_every_mapped_service_resolves_to_real_providers():
    """The service map is the one place a page name becomes providers; a typo
    here would silently produce an empty rail."""
    from app.api.routes.workspace import SERVICE_PROVIDERS

    for service, providers in SERVICE_PROVIDERS.items():
        assert providers, service
        assert all(isinstance(p, Provider) for p in providers), service


# --------------------------------------------- sending (HIGH / irreversible)

def test_send_is_high_risk_irreversible_and_has_no_fake_undo():
    """The properties that make sending safe are all absences and hard limits,
    so they are asserted explicitly rather than assumed."""
    spec = REGISTRY["outlook.send"]
    assert spec.available is True
    assert spec.risk.value == "high"
    assert spec.external is True
    assert spec.needs_approval is True              # never silent
    assert spec.reversibility.value == "irreversible"
    # The absence IS the guarantee: no compensation means no undo button can be
    # offered, which is this module's own rule for what irreversible means.
    assert spec.compensate is None
    # And it can never run unattended, whatever an autonomy policy says.
    assert spec.autonomy_eligible is False
    assert spec.verify is not None                  # still verified after the fact


def test_send_preview_shows_recipients_subject_and_message():
    """What the user confirms is exactly what will go out - and it is stored on
    the action, so the audit record proves what they agreed to."""
    spec = REGISTRY["outlook.send"]
    params = validate_params(spec, {
        "to": ["a@b.com", "c@d.com"], "subject": "Deploy tonight", "body": "Starting at 9pm.",
    })
    preview = spec.preview(params)
    assert preview["to"] == ["a@b.com", "c@d.com"]
    assert preview["subject"] == "Deploy tonight"
    assert preview["message"] == "Starting at 9pm."
    assert preview["sends"] is True and preview["irreversible"] is True
    assert "cannot be recalled" in preview["warning"]


def test_send_preview_truncates_a_very_long_body_but_says_so():
    spec = REGISTRY["outlook.send"]
    params = validate_params(spec, {"to": ["a@b.com"], "subject": "x", "body": "y" * 5000})
    preview = spec.preview(params)
    assert preview["message"].endswith("…") and len(preview["message"]) <= 2001
    assert preview["chars"] == 5000  # the true length is still recorded


def test_send_rejects_invalid_recipients_before_anything_happens():
    spec = REGISTRY["outlook.send"]
    with pytest.raises(Exception):
        validate_params(spec, {"to": ["nope"], "subject": "x", "body": "y"})


def test_unverified_send_is_not_reported_as_success(monkeypatch):
    """If the message cannot be found in Sent Items, the action must say so -
    a send with no confirmation is never dressed up as a success."""
    from app.services import action_registry as ar

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def find_sent(self, subject, since, cap=10): return []

    monkeypatch.setattr(ar, "_outlook_client", lambda session, action: _Client())
    ok, how = REGISTRY["outlook.send"].verify(
        None, None, {"subject": "x", "sent_after": datetime.now(timezone.utc).isoformat()}
    )
    assert ok is False and "no matching message" in how
