"""Phase 3 end-to-end check against the real MySQL database.

Everything happens inside one transaction that is rolled back at the end, and
this script only calls service-layer functions - never route handlers, which
commit internally and would leave real rows behind.

Run: docker compose exec -T backend python scripts/verify_phase3_flow.py
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.channel_required_connection import ChannelRequiredConnection
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.attention_engine import list_attention
from app.services.channel_briefing import build_channel_briefing
from app.services.channel_readiness import member_checklist

NOW = datetime.now(timezone.utc)

passed = failed = 0


def check(label: str, actual, expected) -> None:
    global passed, failed
    ok = actual == expected
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}\n          expected {expected!r}\n          actual   {actual!r}")


session = SessionLocal()
suffix = uuid.uuid4().hex[:8]

try:
    print("\nBuilding a two-member team workspace in MySQL (rolled back at the end)\n")

    workspace = Workspace(name=f"P3 {suffix}", slug=f"p3-{suffix}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    admin = User(email=f"p3-admin-{suffix}@test.local", name="P3 Admin")
    member = User(email=f"p3-member-{suffix}@test.local", name="P3 Member")
    session.add_all([admin, member])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    klass = WorkspaceClass(workspace_id=workspace.id, name="Engineering", slug=f"eng-{suffix}")
    session.add(klass)
    session.flush()
    group = Group(class_id=klass.id, name="Platform", slug=f"platform-{suffix}")
    session.add(group)
    session.flush()
    team = Team(workspace_id=workspace.id, group_id=group.id, name="development", slug=f"dev-{suffix}")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    admin_gmail = Connection(
        workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
        org=f"p3-admin-{suffix}@test.local", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(admin_gmail)
    session.flush()

    session.add(ChannelRequiredConnection(
        team_id=team.id, provider=Provider.GMAIL, is_required=True,
        reason="Client threads live in mail", added_by_user_id=admin.id,
    ))
    session.flush()

    def checklist(user):
        [status] = member_checklist(session, team.id, workspace.id, user.id)
        return status

    # 1. Nothing shared yet: the member genuinely has to connect.
    print("1. Nobody has shared anything")
    s = checklist(member)
    check("member is blocked", s.blocks, True)
    check("no tier provides it", s.provided_by, None)

    # 2. The admin shares their Gmail with the workspace.
    print("\n2. Admin shares their Gmail at the workspace tier")
    shared = SharedConnection(
        scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
        connection_id=admin_gmail.id, added_by_user_id=admin.id,
    )
    session.add(shared)
    session.flush()

    s = checklist(member)
    check("member is no longer blocked", s.blocks, False)
    check("attributed to the workspace tier", s.provided_by, "workspace")
    check("member's own state is still honest", s.state.value, "not_connected")
    check("no account label borrowed from the admin", s.account_label, None)

    # 3. The member joins without connecting anything, and the channel works.
    print("\n3. The member uses the channel without connecting anything")
    session.add(AttentionItem(
        workspace_id=workspace.id, connection_id=admin_gmail.id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=AttentionState.NEW, source_provider="gmail",
        dedupe_key=f"email:p3-team-{suffix}", title="Contract renewal", why="starred", priority=0.7,
    ))
    session.flush()

    briefing = build_channel_briefing(session, team.id, workspace.id)
    check("channel briefing has the shared item", [i.title for i in briefing["items"]], ["Contract renewal"])
    check("channel does not report itself unconfigured", briefing["no_connections"], False)

    # 4. The member opts in privately.
    print("\n4. The member connects their own Gmail privately")
    member_gmail = Connection(
        workspace_id=workspace.id, user_id=member.id, provider=Provider.GMAIL,
        org=f"p3-member-{suffix}@test.local", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(member_gmail)
    session.flush()
    session.add(AttentionItem(
        workspace_id=workspace.id, connection_id=member_gmail.id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=AttentionState.NEW, source_provider="gmail",
        dedupe_key=f"email:p3-private-{suffix}", title="Medical results ready", why="starred", priority=0.7,
    ))
    session.flush()

    check("their own state now reads connected", checklist(member).state.value, "ready")
    check("still attributed to the shared tier", checklist(member).provided_by, "workspace")

    print("\n5. Where that private mail can and cannot appear")
    briefing = build_channel_briefing(session, team.id, workspace.id)
    check("private item stays out of the channel", [i.title for i in briefing["items"]], ["Contract renewal"])

    member_list = [i.title for i in list_attention(session, workspace.id, viewer_user_id=member.id)]
    admin_list = [i.title for i in list_attention(session, workspace.id, viewer_user_id=admin.id)]
    check("member sees their own private item", member_list, ["Medical results ready"])
    check("admin does not, despite being ORG_ADMIN", admin_list, ["Contract renewal"])

    # 6. Fail-closed still holds where it should.
    print("\n6. Fail-closed checks")
    other_ws = Workspace(name=f"Other {suffix}", slug=f"other-{suffix}", kind=WorkspaceKind.ORGANIZATION)
    session.add(other_ws)
    session.flush()
    session.add(SharedConnection(
        scope_type=SharedScope.WORKSPACE, scope_id=other_ws.id,
        connection_id=member_gmail.id, added_by_user_id=member.id,
    ))
    session.flush()
    check("a share in another workspace changes nothing here",
          [i.title for i in build_channel_briefing(session, team.id, workspace.id)["items"]],
          ["Contract renewal"])

    session.delete(shared)
    session.flush()
    check("unsharing re-blocks the member", checklist(member).provided_by, None)
    check("unsharing empties the channel", build_channel_briefing(session, team.id, workspace.id)["items"], [])

finally:
    session.rollback()

    # Prove the rollback took: none of this may survive in the real database.
    verify = SessionLocal()
    leftovers = {
        "workspaces": verify.execute(select(Workspace).where(Workspace.slug.like(f"%{suffix}%"))).scalars().all(),
        "users": verify.execute(select(User).where(User.email.like(f"%{suffix}%"))).scalars().all(),
        "attention_items": verify.execute(select(AttentionItem).where(AttentionItem.dedupe_key.like(f"%{suffix}%"))).scalars().all(),
        "shared_connections": verify.execute(
            select(SharedConnection).join(Connection, Connection.id == SharedConnection.connection_id)
            .where(Connection.org.like(f"%{suffix}%"))
        ).scalars().all(),
    }
    verify.close()
    session.close()

    print("\nRollback verification (all must be 0):")
    for table, rows in leftovers.items():
        status = "OK" if not rows else "LEFTOVER ROWS"
        print(f"  {status}  {table}: {len(rows)}")
        if rows:
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
