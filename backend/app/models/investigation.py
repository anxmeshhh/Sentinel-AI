"""A cached investigation of one attention item.

Same reasoning as MeetingBrief and EmailSummary: the expensive part
(deterministic retrieval plus one LLM synthesis) runs once, and re-opening
the same investigation costs zero tokens.

Keyed by `(workspace, attention_item, scope_key)` rather than by item alone,
because the *same* item investigated from two places is legitimately two
different investigations: a channel investigation may only draw on that
channel's authorized connections, while a personal one draws on the viewer's
own. Caching them under one key would let the first caller's evidence be
served to the second - a cache that leaks across an authorization boundary.
`scope_key` is "personal:{user_id}" or "channel:{team_id}".
"""

import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class Investigation(Base, UUIDPk, TimestampMixin):
    __tablename__ = "investigations"
    __table_args__ = (
        UniqueConstraint("attention_item_id", "scope_key", name="uq_investigation_item_scope"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    attention_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("attention_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which authorization scope produced it - see the module docstring.
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # --- AI inference. Every field below is the model's reading of the
    # evidence, and the UI labels it as such. None of it is a stored fact.
    what_happened: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    contributing_factors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 0..1. Reported rather than hidden: an investigation over two weak
    # signals should say so instead of sounding equally sure as one over ten.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # --- Verified facts. Retrieved deterministically from Signals, never
    # produced by the model, each carrying its own link. This is what makes a
    # claim checkable instead of something the user must take on faith.
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # How the answer was reached, for the UI's "how I looked" trail.
    llm_calls: Mapped[int] = mapped_column(nullable=False, default=0)
