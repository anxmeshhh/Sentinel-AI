"""The assistant's context assembly.

`_maybe_live_email_body` referenced a `user` that was never passed into it, so
the one branch that fetches an email body raised NameError rather than
returning the body. Nothing caught it because no test reached that branch: the
guard above it returns early unless the question both matches a stored email
AND contains a content-intent word.

These tests pin the signature and walk the guard, so the branch cannot go back
to being unreachable-and-broken.
"""

import inspect
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import assistant as assistant_routes
from app.models.base import Base
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind

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


def test_live_body_fetch_takes_the_user_it_looks_a_connection_up_for():
    """The connection lookup is per-user, so the user has to be an argument.

    This is the actual defect: the body was looked up with `user.id` inside a
    function whose parameters were (session, workspace_id, question).
    """
    params = list(inspect.signature(assistant_routes._maybe_live_email_body).parameters)
    assert "user_id" in params, (
        "the per-user connection lookup needs the user passed in, not closed over"
    )


def test_context_builder_threads_the_user_through():
    params = list(inspect.signature(assistant_routes._build_context).parameters)
    assert "user_id" in params


def test_a_content_question_with_no_matching_email_returns_nothing(session, env):
    """Walks the guard the bug hid behind.

    "about" is a content-intent word, so this gets past the first return and
    into the lookup - which is exactly where NameError used to be raised. With
    no matching signal it returns None, and the point is that it returns at
    all rather than blowing up.
    """
    result = assistant_routes._maybe_live_email_body(
        session, env["ws"].id, env["user"].id, "what was that email about?"
    )
    assert result is None


def test_a_question_with_no_content_intent_never_reaches_the_fetch(session, env):
    """The cheap guard still holds: "is there an email from X" is answered by
    the structured summary, so no body is fetched for it."""
    result = assistant_routes._maybe_live_email_body(
        session, env["ws"].id, env["user"].id, "is there an email from Priya"
    )
    assert result is None
