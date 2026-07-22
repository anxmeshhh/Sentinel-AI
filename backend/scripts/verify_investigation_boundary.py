"""Prove the Individual/Collective boundary on the real database.

Builds a second member with their own private mailbox inside a real
workspace, plants a decoy that would match the anchor on every correlation
relationship, and checks that neither scope can reach it.

Cleanup is explicit deletion, NOT rollback. `investigate()` writes a cache
row and commits to do it, which ends the probe's transaction - so a rollback
at the end reverts nothing and leaves a whole fake workspace behind. That is
exactly what happened the first time this script was run, and it is the same
trap the Phase 2 sharing probe fell into. Any probe that calls a function
which commits has to clean up after itself by name, and then prove it did.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.attention_item import AttentionItem
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.signal import Signal, SignalType
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.investigation import NotAuthorized, channel_scope, investigate, personal_scope

NOW = datetime.now(timezone.utc)
passed = failed = 0


def check(label, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}\n          expected {expected!r}\n          actual   {actual!r}")


def _cleanup(suffix: str) -> None:
    """Delete everything this probe created, in FK-safe order."""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        ids = [row[0] for row in db.execute(
            text("SELECT id FROM workspaces WHERE slug LIKE :s"), {"s": f"%{suffix}%"}
        )]
        for workspace_id in ids:
            db.execute(text("DELETE i FROM investigations i WHERE i.workspace_id = :w"), {"w": workspace_id})
            db.execute(text("DELETE FROM attention_items WHERE workspace_id = :w"), {"w": workspace_id})
            db.execute(text("DELETE FROM signals WHERE workspace_id = :w"), {"w": workspace_id})
            db.execute(text(
                "DELETE sc FROM shared_connections sc JOIN connections c ON c.id = sc.connection_id "
                "WHERE c.workspace_id = :w"
            ), {"w": workspace_id})
            db.execute(text("DELETE FROM connections WHERE workspace_id = :w"), {"w": workspace_id})
            db.execute(text(
                "DELETE FROM team_memberships WHERE team_id IN (SELECT id FROM teams WHERE workspace_id = :w)"
            ), {"w": workspace_id})
            db.execute(text("DELETE FROM teams WHERE workspace_id = :w"), {"w": workspace_id})
            db.execute(text(
                "DELETE FROM workspace_groups WHERE class_id IN "
                "(SELECT id FROM workspace_classes WHERE workspace_id = :w)"
            ), {"w": workspace_id})
            db.execute(text("DELETE FROM workspace_classes WHERE workspace_id = :w"), {"w": workspace_id})
            db.execute(text("DELETE FROM memberships WHERE workspace_id = :w"), {"w": workspace_id})
            db.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
        db.execute(text("DELETE FROM users WHERE email LIKE :s"), {"s": f"%{suffix}%"})
        db.commit()
    finally:
        db.close()


session = SessionLocal()
suffix = uuid.uuid4().hex[:8]

try:
    ws = Workspace(name=f"INV {suffix}", slug=f"inv-{suffix}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()

    admin = User(email=f"inv-admin-{suffix}@t.local", name="Admin")
    member = User(email=f"inv-member-{suffix}@t.local", name="Member")
    session.add_all([admin, member])
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=admin.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=ws.id, user_id=member.id, role=Role.EMPLOYEE))

    klass = WorkspaceClass(workspace_id=ws.id, name="Eng", slug=f"eng-{suffix}")
    session.add(klass)
    session.flush()
    grp = Group(class_id=klass.id, name="Plat", slug=f"plat-{suffix}")
    session.add(grp)
    session.flush()
    team = Team(workspace_id=ws.id, group_id=grp.id, name="dev", slug=f"dev-{suffix}")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    admin_mail = Connection(workspace_id=ws.id, user_id=admin.id, provider=Provider.GMAIL,
                            org=f"inv-admin-{suffix}@t.local", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    member_mail = Connection(workspace_id=ws.id, user_id=member.id, provider=Provider.GMAIL,
                             org=f"inv-member-{suffix}@t.local", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    session.add_all([admin_mail, member_mail])
    session.flush()
    session.add(SharedConnection(scope_type=SharedScope.WORKSPACE, scope_id=ws.id,
                                 connection_id=admin_mail.id, added_by_user_id=admin.id))

    def sig(conn, ext, subject, actor, when=NOW, thread="t-deploy"):
        return Signal(workspace_id=ws.id, connection_id=conn.id, type=SignalType.EMAIL, external_id=ext,
                      actor=actor, occurred_at=when,
                      payload={"subject": subject, "from": actor, "thread_id": thread, "label_ids": ["UNREAD"]})

    session.add_all([
        sig(admin_mail, f"dep-{suffix}", "Production deployment failed", "CI <ci@acme.test>"),
        sig(admin_mail, f"rep-{suffix}", "Re: Production deployment failed", "Dev <dev@acme.test>"),
        # The decoy: same thread, same sender, same subject, same hour -
        # matches every correlation relationship. Only the mailbox differs.
        sig(member_mail, f"priv-{suffix}", "Production deployment failed - PRIVATE MEMBER COPY", "CI <ci@acme.test>"),
    ])

    item = AttentionItem(
        workspace_id=ws.id, connection_id=admin_mail.id, type=__import__(
            "app.models.attention_item", fromlist=["AttentionType"]).AttentionType.IMPORTANT_EMAIL,
        origin=__import__("app.models.attention_item", fromlist=["AttentionOrigin"]).AttentionOrigin.DETECTED,
        state=__import__("app.models.attention_item", fromlist=["AttentionState"]).AttentionState.NEW,
        source_provider="gmail", dedupe_key=f"email:dep-{suffix}", title="Production deployment failed",
        why="starred, unread", priority=0.8,
    )
    session.add(item)
    session.flush()

    print("\nA decoy matching on thread + sender + subject + time sits in the member's private mailbox.\n")

    print("1. Admin investigates in their own personal scope")
    result = investigate(session, item=item, scope=personal_scope(session, ws.id, admin.id))
    titles = [e["title"] for e in result.evidence]
    check("found the real reply", any("Re: Production" in t for t in titles), True)
    check("did NOT reach the member's private copy", any("PRIVATE MEMBER COPY" in t for t in titles), False)

    print("\n2. The member investigates inside the channel (they are the caller)")
    result = investigate(session, item=item, scope=channel_scope(session, team.id))
    titles = [e["title"] for e in result.evidence]
    check("channel sees the shared thread", any("Re: Production" in t for t in titles), True)
    check("caller's own private mail did NOT ride along", any("PRIVATE MEMBER COPY" in t for t in titles), False)

    print("\n3. Scopes cache separately")
    p = investigate(session, item=item, scope=personal_scope(session, ws.id, admin.id))
    c = investigate(session, item=item, scope=channel_scope(session, team.id))
    check("two rows, not one", p.id != c.id, True)

    print("\n4. Nobody can investigate what they cannot see")
    priv_item = AttentionItem(
        workspace_id=ws.id, connection_id=member_mail.id,
        type=item.type, origin=item.origin, state=item.state, source_provider="gmail",
        dedupe_key=f"email:priv-{suffix}", title="Private member thing", why="starred", priority=0.5,
    )
    session.add(priv_item)
    session.flush()
    try:
        investigate(session, item=priv_item, scope=personal_scope(session, ws.id, admin.id))
        check("admin refused the member's private item", "allowed", "refused")
    except NotAuthorized:
        check("admin refused the member's private item", "refused", "refused")

finally:
    session.rollback()
    _cleanup(suffix)
    session.close()

    verify = SessionLocal()
    leftover = {
        "workspaces": verify.execute(select(Workspace).where(Workspace.slug.like(f"%{suffix}%"))).scalars().all(),
        "users": verify.execute(select(User).where(User.email.like(f"%{suffix}%"))).scalars().all(),
        "attention_items": verify.execute(
            select(AttentionItem).where(AttentionItem.dedupe_key.like(f"%{suffix}%"))
        ).scalars().all(),
    }
    verify.close()

    print("\nCleanup verification (all must be 0):")
    for table, rows in leftover.items():
        print(f"  {'OK ' if not rows else 'LEFTOVER'}  {table}: {len(rows)}")
        if rows:
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
