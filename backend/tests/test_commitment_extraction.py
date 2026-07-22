"""Extraction from prose: the gates, not the model.

The model is stubbed throughout. What is under test is everything around it -
which bodies are even opened, what happens to an uncertain answer, whether an
owner is resolved or left unattributed, and whether anything read from a
message survives beyond the prompt. Those are the parts that decide whether
this feature is trustworthy; the model's own accuracy on real prose is
unmeasured and not claimed anywhere.

Grounding measurement: promise language appeared in 2 of 40 real bodies, and
both were false positives (a job advert, and a webinar mail saying "we will
send you the recording"). That is why the default outcome of an uncertain
extraction is a question rather than a record.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.commitment import Commitment, CommitmentSource, CommitmentStatus
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.signal import Signal, SignalType
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services import commitment_extraction as extraction
from app.services.commitments import confirm_commitment, list_commitments
from app.services.investigation import channel_scope, personal_scope

NOW = datetime.now(timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def env(session):
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    admin = User(email="admin@acme.test", name="Admin Person")
    member = User(email="rahul@acme.test", name="Rahul Sharma")
    session.add_all([admin, member])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    klass = WorkspaceClass(workspace_id=workspace.id, name="Eng", slug="eng")
    session.add(klass)
    session.flush()
    group = Group(class_id=klass.id, name="Plat", slug="plat")
    session.add(group)
    session.flush()
    team = Team(workspace_id=workspace.id, group_id=group.id, name="dev", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    admin_gmail = Connection(workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
                             org="admin@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    member_gmail = Connection(workspace_id=workspace.id, user_id=member.id, provider=Provider.GMAIL,
                              org="rahul@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    session.add_all([admin_gmail, member_gmail])
    session.flush()
    session.add(SharedConnection(scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
                                 connection_id=admin_gmail.id, added_by_user_id=admin.id))
    session.commit()

    return {"workspace": workspace, "team": team, "admin": admin, "member": member,
            "admin_gmail": admin_gmail, "member_gmail": member_gmail}


def _email(connection, external_id, subject, *, sender="colleague@partner.test", bulk=False, days_ago=1):
    return Signal(
        workspace_id=connection.workspace_id, connection_id=connection.id, type=SignalType.EMAIL,
        external_id=external_id, actor=f"Someone <{sender}>", occurred_at=NOW - timedelta(days=days_ago),
        payload={"subject": subject, "from": f"Someone <{sender}>", "to": connection.org,
                 "thread_id": external_id, "label_ids": ["UNREAD"], "is_bulk": bulk},
    )


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace the model with a scripted answer, so the gates are what's tested."""
    calls = {"n": 0}

    def install(answer):
        class _Client:
            def complete_json(self, **_kwargs):
                calls["n"] += 1
                return answer

        monkeypatch.setattr(extraction, "LLMClient", _Client)
        return calls

    return install


@pytest.fixture
def stub_body(monkeypatch):
    """Provide a body without touching Gmail."""
    def install(text):
        monkeypatch.setattr(extraction, "_fetch_body", lambda _s, _c, _sig: text)
    return install


HIGH = {"found": True, "action": "Send the revised proposal", "owner": "rahul@acme.test",
        "due": (NOW + timedelta(days=2)).date().isoformat(), "confidence": 0.92}
LOW = {"found": True, "action": "Maybe look at the deck", "owner": None, "due": None, "confidence": 0.55}
NONE = {"found": False, "action": "", "owner": None, "due": None, "confidence": 0.0}


# --- the gates -------------------------------------------------------------


def test_bulk_mail_is_never_even_opened(session, env, stub_llm, stub_body):
    """The highest-value filter, and the one the measurement demanded: the
    only real-world matches were a newsletter and a job advert."""
    session.add(_email(env["admin_gmail"], "b1", "Webinar tomorrow", bulk=True))
    session.commit()
    calls = stub_llm(HIGH)
    stub_body("We will send you the recording after the session.")

    created = extraction.extract_commitments(session, env["workspace"].id, personal_scope(session, env["workspace"].id, env["admin"].id))

    assert created == []
    assert calls["n"] == 0  # no body fetched, no model call


def test_a_body_without_promise_language_costs_no_model_call(session, env, stub_llm, monkeypatch):
    """Gate 2: the subject looked plausible, the body doesn't.

    This exercises the *real* `_fetch_body`, stubbing only the network, so
    the promise filter inside it is what decides - stubbing `_fetch_body`
    itself would test nothing.
    """
    session.add(_email(env["admin_gmail"], "b2", "Quick question"))
    session.commit()
    calls = stub_llm(HIGH)

    class _FakeGmail:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def fetch_message_body(self, _external_id):
            return "Thanks for the update, looks good to me."  # no promise

    monkeypatch.setattr("app.integrations.gmail_client.GmailClient", _FakeGmail)
    monkeypatch.setattr("app.integrations.google_auth.get_valid_access_token", lambda _s, _c: "token")

    created = extraction.extract_commitments(
        session, env["workspace"].id, personal_scope(session, env["workspace"].id, env["admin"].id)
    )

    assert created == []
    assert calls["n"] == 0  # the body was read, and rejected, without the model


def test_a_body_with_promise_language_does_reach_the_model(session, env, stub_llm, monkeypatch):
    """The other half - proving the test above fails for the right reason."""
    session.add(_email(env["admin_gmail"], "b2b", "Re: proposal"))
    session.commit()
    calls = stub_llm(HIGH)

    class _FakeGmail:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def fetch_message_body(self, _external_id):
            return "I'll send the revised proposal by Thursday."

    monkeypatch.setattr("app.integrations.gmail_client.GmailClient", _FakeGmail)
    monkeypatch.setattr("app.integrations.google_auth.get_valid_access_token", lambda _s, _c: "token")

    created = extraction.extract_commitments(
        session, env["workspace"].id, personal_scope(session, env["workspace"].id, env["admin"].id)
    )

    assert len(created) == 1
    assert calls["n"] == 1


def test_found_false_creates_nothing(session, env, stub_llm, stub_body):
    """"No commitment here" is the expected answer, and must cost nothing."""
    session.add(_email(env["admin_gmail"], "b3", "Re: project"))
    session.commit()
    stub_llm(NONE)
    stub_body("I'll be out of office next week.")

    created = extraction.extract_commitments(
        session, env["workspace"].id, personal_scope(session, env["workspace"].id, env["admin"].id)
    )

    assert created == []
    assert session.execute(select(Commitment)).scalars().all() == []


def test_low_confidence_asks_instead_of_asserting(session, env, stub_llm, stub_body):
    """The heart of it. Sentinel suspecting something is not Sentinel
    claiming it."""
    session.add(_email(env["admin_gmail"], "b4", "Re: deck"))
    session.commit()
    stub_llm(LOW)
    stub_body("We should probably look at the deck at some point.")

    [commitment] = extraction.extract_commitments(
        session, env["workspace"].id, personal_scope(session, env["workspace"].id, env["admin"].id)
    )

    assert commitment.status == CommitmentStatus.SUGGESTED
    assert commitment.source == CommitmentSource.EXTRACTED


def test_high_confidence_is_tracked_outright(session, env, stub_llm, stub_body):
    session.add(_email(env["admin_gmail"], "b5", "Re: proposal"))
    session.commit()
    stub_llm(HIGH)
    stub_body("I'll send the revised proposal by Thursday.")

    [commitment] = extraction.extract_commitments(
        session, env["workspace"].id, personal_scope(session, env["workspace"].id, env["admin"].id)
    )

    assert commitment.status != CommitmentStatus.SUGGESTED
    assert commitment.what == "Send the revised proposal"


def test_a_suggestion_never_ages_into_an_obligation(session, env, stub_llm, stub_body):
    """An unanswered question turning itself OVERDUE would be Sentinel
    asserting exactly what it was unsure enough to ask about."""
    from app.services.commitments import refresh_commitments

    session.add(_email(env["admin_gmail"], "b6", "Re: deck"))
    session.commit()
    stub_llm({**LOW, "due": (NOW - timedelta(days=5)).date().isoformat()})
    stub_body("We should probably look at the deck.")
    scope = personal_scope(session, env["workspace"].id, env["admin"].id)
    [commitment] = extraction.extract_commitments(session, env["workspace"].id, scope)

    refresh_commitments(session, env["workspace"].id, scope)

    session.refresh(commitment)
    assert commitment.status == CommitmentStatus.SUGGESTED


def test_confirming_a_suggestion_promotes_it(session, env, stub_llm, stub_body):
    session.add(_email(env["admin_gmail"], "b7", "Re: deck"))
    session.commit()
    stub_llm({**LOW, "due": (NOW + timedelta(hours=10)).isoformat()})
    stub_body("We should look at the deck.")
    scope = personal_scope(session, env["workspace"].id, env["admin"].id)
    [commitment] = extraction.extract_commitments(session, env["workspace"].id, scope)

    confirmed = confirm_commitment(session, commitment)

    assert confirmed.status == CommitmentStatus.DUE_SOON  # now ages normally
    assert confirmed.confidence == 1.0


def test_re_running_does_not_duplicate_or_resurrect(session, env, stub_llm, stub_body):
    """Re-extraction must not bring back something a person dismissed."""
    from app.services.commitments import dismiss_commitment

    session.add(_email(env["admin_gmail"], "b8", "Re: proposal"))
    session.commit()
    stub_llm(HIGH)
    stub_body("I'll send the revised proposal by Thursday.")
    scope = personal_scope(session, env["workspace"].id, env["admin"].id)
    [commitment] = extraction.extract_commitments(session, env["workspace"].id, scope)
    dismiss_commitment(session, commitment)

    again = extraction.extract_commitments(session, env["workspace"].id, scope)

    assert again == []
    assert len(session.execute(select(Commitment)).scalars().all()) == 1
    assert list_commitments(session, scope) == []


# --- privacy ---------------------------------------------------------------


def test_no_message_text_is_ever_stored(session, env, stub_llm, stub_body):
    """The invariant this feature had to preserve to be allowed to exist."""
    secret = "I'll wire the settlement of 45000 to the account ending 8891 by Friday."
    session.add(_email(env["admin_gmail"], "b9", "Re: settlement"))
    session.commit()
    stub_llm(HIGH)
    stub_body(secret)
    scope = personal_scope(session, env["workspace"].id, env["admin"].id)

    [commitment] = extraction.extract_commitments(session, env["workspace"].id, scope)

    serialized = str({
        "what": commitment.what, "evidence": commitment.evidence,
        "owner": commitment.owner_label, "reason": commitment.resolution_reason,
    })
    assert "45000" not in serialized
    assert "8891" not in serialized
    assert "settlement of" not in serialized
    # The signal it came from is cited, not copied.
    assert commitment.evidence[0]["signal_id"]
    signal = session.get(Signal, uuid.UUID(commitment.evidence[0]["signal_id"]))
    assert "body" not in (signal.payload or {})
    assert "content" not in (signal.payload or {})


def test_a_private_message_never_becomes_a_channel_commitment(session, env, stub_llm, stub_body):
    """ATTACK: the member's own mailbox is not shared. A promise in it is
    theirs, and the channel must extract nothing from it."""
    session.add(_email(env["member_gmail"], "p1", "Re: my side project"))
    session.commit()
    stub_llm(HIGH)
    stub_body("I'll send the revised proposal by Thursday.")

    created = extraction.extract_commitments(
        session, env["workspace"].id, channel_scope(session, env["team"].id)
    )

    assert created == []


# --- owner identity --------------------------------------------------------


def test_an_exact_email_match_resolves_the_owner(session, env):
    resolved = extraction.resolve_owner(session, env["workspace"].id, "rahul@acme.test", "Rahul")

    assert resolved == env["member"].id


def test_an_unknown_email_resolves_to_nobody(session, env):
    assert extraction.resolve_owner(session, env["workspace"].id, "someone@elsewhere.test", "Someone") is None


def test_a_full_name_resolves_only_when_unambiguous(session, env):
    assert extraction.resolve_owner(session, env["workspace"].id, None, "Rahul Sharma") == env["member"].id


def test_an_ambiguous_name_is_never_guessed(session, env, session_maker=None):
    """Two people answering to the same name make every guess a coin flip,
    and attaching a promise to the wrong colleague is worse than attaching it
    to nobody - they would never see it, and someone else gets chased."""
    twin = User(email="rahul2@acme.test", name="Rahul Sharma")
    session.add(twin)
    session.flush()
    session.add(Membership(workspace_id=env["workspace"].id, user_id=twin.id, role=Role.EMPLOYEE))
    session.commit()

    assert extraction.resolve_owner(session, env["workspace"].id, None, "Rahul Sharma") is None


def test_a_first_name_alone_is_not_an_identity(session, env):
    assert extraction.resolve_owner(session, env["workspace"].id, None, "Rahul") is None


def test_a_member_of_another_workspace_is_not_resolved(session, env):
    other = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(other)
    session.flush()
    outsider = User(email="outsider@other.test", name="Outsider")
    session.add(outsider)
    session.flush()
    session.add(Membership(workspace_id=other.id, user_id=outsider.id, role=Role.EMPLOYEE))
    session.commit()

    assert extraction.resolve_owner(session, env["workspace"].id, "outsider@other.test", "Outsider") is None
