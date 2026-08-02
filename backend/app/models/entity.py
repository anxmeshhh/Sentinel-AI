"""The Entity Layer - Intelligence Core, Phase 2.

An Entity is a canonical operational noun the org runs on: a repository, a
channel, a service, a person. It is the substrate that makes correlation
possible - Slack's "#deploys", GitHub's "acme/api" and a calendar "API deploy"
can only become one Situation if they first resolve to shared Entities.

An EntityMention links one canonical Finding (by its stable string id, e.g.
"attention:<uuid>") to one Entity, recording *how* the finding relates to it.
Mentions are re-derived deterministically from findings every refresh - never
model-written - so the whole chain Situation -> Finding -> Signal stays
traceable and provider-agnostic.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk, utcnow


class EntityKind(str, enum.Enum):
    REPO = "repo"  # a code repository (GitHub)
    CHANNEL = "channel"  # a chat channel (Slack)
    SERVICE = "service"  # an external service the org depends on (Supabase, Vercel, ...)
    PERSON = "person"  # a human actor (author, sender, attendee)


# The strong entities - the ones meaningful enough to anchor a Situation. A
# person is a real entity but a weak correlator (two findings mentioning the
# same person is usually coincidence), so correlation ignores PERSON.
STRONG_KINDS = (EntityKind.REPO, EntityKind.CHANNEL, EntityKind.SERVICE)


class MentionRole(str, enum.Enum):
    ABOUT = "about"  # the finding is primarily about this resource (the repo/channel/service it concerns)
    ACTOR = "actor"  # a person who acted in the finding (PR author, email sender)
    MENTIONS = "mentions"  # this entity's name appears in the finding's text - a weaker, cross-provider link


class Entity(Base, UUIDPk, TimestampMixin):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "key", name="uq_entity_ws_kind_key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    kind: Mapped[EntityKind] = mapped_column(Enum(EntityKind, name="entity_kind"), nullable=False)
    # Canonical, provider-prefixed and stable: "github:acme/api", "slack:C0123",
    # "service:supabase", "person:jane@acme.test". The prefix is what keeps two
    # providers' identical-looking names from colliding.
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class EntityMention(Base, UUIDPk, TimestampMixin):
    __tablename__ = "entity_mentions"
    __table_args__ = (UniqueConstraint("finding_id", "entity_id", "role", name="uq_mention_finding_entity_role"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)

    # The canonical Finding this mention is for, by its stable string id
    # ("attention:<uuid>" / "situation:<uuid>"). Not a DB FK because findings
    # are a read model over two tables (Phase 1); the string is the stable
    # reference, and stale mentions are pruned each refresh.
    finding_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    finding_source: Mapped[str] = mapped_column(String(20), nullable=False)

    role: Mapped[MentionRole] = mapped_column(Enum(MentionRole, name="mention_role"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
