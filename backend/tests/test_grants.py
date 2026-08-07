"""The generalized Grant abstraction (Microsoft sprint, N=2).

One provisioner, two workspace-providers. These prove Google's exact prior
behaviour is preserved AND that Microsoft flows through the identical path:
right child connections, keyed per (workspace, user, provider); idempotent
re-consent; a different account purges the now-unreadable signals (and mail
summaries); revocation cleared on reconnect.
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.email_summary import EmailSummary
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.providers.workspace_grants import GOOGLE_GRANT, MICROSOFT_GRANT
from app.services.grants import provision_grant


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
    a = User(email="a@acme.test", name="A")
    b = User(email="b@acme.test", name="B")
    session.add_all([a, b])
    session.flush()
    session.add_all([
        Membership(workspace_id=ws.id, user_id=a.id, role=Role.ORG_ADMIN),
        Membership(workspace_id=ws.id, user_id=b.id, role=Role.EMPLOYEE),
    ])
    session.commit()
    return {"ws": ws, "a": a, "b": b}


def _providers(session, ws_id, user_id):
    return sorted(
        c.provider.value for c in session.execute(
            select(Connection).where(Connection.workspace_id == ws_id, Connection.user_id == user_id)
        ).scalars().all()
    )


def test_google_grant_provisions_its_three_services(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=GOOGLE_GRANT,
                    account_identity="a@gmail.com", encrypted_token="tok")
    assert _providers(session, env["ws"].id, env["a"].id) == ["gmail", "google_calendar", "google_drive"]


def test_microsoft_grant_provisions_its_services_via_the_same_path(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=MICROSOFT_GRANT,
                    account_identity="a@contoso.com", encrypted_token="tok")
    # Five fixed services plus the Teams ANCHOR: Teams reaches many channels, so
    # the grant records the account and leaves the choosing to the user.
    assert _providers(session, env["ws"].id, env["a"].id) == [
        "microsoft_onedrive", "microsoft_onenote", "microsoft_outlook_calendar",
        "microsoft_outlook_mail", "microsoft_teams", "microsoft_todo",
    ]
    # Child connections share the grant's token + identity, and carry the service label.
    conns = session.execute(select(Connection).where(Connection.user_id == env["a"].id)).scalars().all()
    assert all(c.org == "a@contoso.com" and c.encrypted_token == "tok" for c in conns)
    assert {c.repo for c in conns} == {"mail", "calendar", "onedrive", "onenote", "todo", ""}  # "" = Teams anchor


def test_reprovision_same_account_is_idempotent_and_clears_revocation(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=MICROSOFT_GRANT,
                    account_identity="a@contoso.com", encrypted_token="tok1")
    mail = session.execute(select(Connection).where(Connection.provider == Provider.MICROSOFT_OUTLOOK_MAIL)).scalar_one()
    from datetime import datetime, timezone
    mail.revoked_at = datetime.now(timezone.utc)
    session.commit()

    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=MICROSOFT_GRANT,
                    account_identity="a@contoso.com", encrypted_token="tok2")
    conns = session.execute(select(Connection).where(Connection.user_id == env["a"].id)).scalars().all()
    assert len(conns) == 6  # five services + Teams anchor, not duplicated
    refreshed = session.get(Connection, mail.id)
    assert refreshed.encrypted_token == "tok2" and refreshed.revoked_at is None


def test_different_account_purges_signals_and_mail_summaries(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=MICROSOFT_GRANT,
                    account_identity="old@contoso.com", encrypted_token="tok")
    mail = session.execute(select(Connection).where(Connection.provider == Provider.MICROSOFT_OUTLOOK_MAIL)).scalar_one()
    session.add(Signal(workspace_id=env["ws"].id, connection_id=mail.id, type=SignalType.EMAIL,
                       external_id="m1", actor="x", payload={}, occurred_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
    session.add(EmailSummary(workspace_id=env["ws"].id, message_id="m1", subject="s", sender="x",
                             summary="sum", key_points=[], action_items=[]))
    session.commit()

    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=MICROSOFT_GRANT,
                    account_identity="new@contoso.com", encrypted_token="tok")
    assert session.execute(select(Signal).where(Signal.connection_id == mail.id)).scalars().all() == []
    assert session.execute(select(EmailSummary)).scalars().all() == []
    assert session.get(Connection, mail.id).org == "new@contoso.com"


def test_grant_is_scoped_per_user(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["a"].id, grant=MICROSOFT_GRANT,
                    account_identity="a@contoso.com", encrypted_token="tokA")
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["b"].id, grant=MICROSOFT_GRANT,
                    account_identity="b@contoso.com", encrypted_token="tokB")
    # Two members, no collision - each owns their own six connections.
    assert len(_providers(session, env["ws"].id, env["a"].id)) == 6
    assert len(_providers(session, env["ws"].id, env["b"].id)) == 6
    assert session.execute(select(Connection)).scalars().all().__len__() == 12
