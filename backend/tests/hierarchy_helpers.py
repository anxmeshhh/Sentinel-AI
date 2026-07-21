"""Shared test helper for Phase 2y.

A Channel now requires a parent Group, so every test that builds one needs a
Class and a Group first. That scaffolding says nothing about what those tests
are actually asserting, so it lives here rather than being pasted into a
dozen fixtures.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.hierarchy import Group, WorkspaceClass


def make_group(session: Session, workspace_id: uuid.UUID, *, class_name: str = "General", group_name: str = "General") -> Group:
    """A Class + Group pair inside `workspace_id`, returning the Group.

    Slugs are randomized because these fixtures often build several
    workspaces per test and the uniqueness constraints are scoped to
    (workspace, slug) and (class, slug).
    """
    suffix = uuid.uuid4().hex[:8]
    workspace_class = WorkspaceClass(
        workspace_id=workspace_id, name=class_name, slug=f"{class_name.lower()}-{suffix}"
    )
    session.add(workspace_class)
    session.flush()

    group = Group(class_id=workspace_class.id, name=group_name, slug=f"{group_name.lower()}-{suffix}")
    session.add(group)
    session.flush()
    return group
