"""Structured Gmail browsing + a thin rule-based ask-bar (see mail_query.py
docstring for why this is deliberately not a freeform query engine).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.models.connection import Provider
from app.models.signal import Signal, SignalType
from app.repositories.connections import ConnectionRepository
from app.schemas.mail import MailAskRequest, MailAskResponse, MailBodyOut, MailItemOut
from app.services.mail_query import MAIL_FILTERS, list_mail, match_mail_intent

router = APIRouter(prefix="/mail", tags=["mail"])


@router.get("", response_model=list[MailItemOut])
def get_mail(
    filter: str = "recent",
    category: str | None = None,
    limit: int = 30,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[MailItemOut]:
    if filter not in MAIL_FILTERS:
        raise HTTPException(status_code=400, detail=f"Unknown filter. Use one of: {sorted(MAIL_FILTERS)}")
    try:
        signals = list_mail(session, workspace_id, mail_filter=filter, category=category, limit=min(limit, 100))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [_to_item(s) for s in signals]


@router.post("/ask", response_model=MailAskResponse)
def ask_mail(
    payload: MailAskRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> MailAskResponse:
    matched = match_mail_intent(payload.question)
    if matched is None:
        return MailAskResponse(
            matched_filter=None,
            matched_category=None,
            items=[],
            message="Not sure what you're asking — try: recent, starred, spam, important, unread, or top 10.",
        )
    mail_filter, category = matched
    signals = list_mail(session, workspace_id, mail_filter=mail_filter, category=category, limit=10)
    return MailAskResponse(matched_filter=mail_filter, matched_category=category, items=[_to_item(s) for s in signals])


@router.get("/{signal_id}/body", response_model=MailBodyOut)
def get_mail_body(
    signal_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> MailBodyOut:
    """Live, on-demand fetch - the body is never read from or written to
    storage, see gmail_client.py's module docstring.
    """
    signal = session.get(Signal, signal_id)
    if signal is None or signal.workspace_id != workspace_id or signal.type != SignalType.EMAIL:
        raise HTTPException(status_code=404, detail="Email not found")

    connection = ConnectionRepository(session, workspace_id).get_by_provider(Provider.GMAIL)
    if connection is None:
        raise HTTPException(status_code=404, detail="Gmail is not connected")

    access_token = get_valid_access_token(session, connection)
    with GmailClient(access_token) as client:
        body_text = client.fetch_message_body(signal.external_id)

    return MailBodyOut(
        subject=signal.payload.get("subject", "(no subject)"),
        sender=signal.payload.get("from", "unknown"),
        body_text=body_text,
    )


def _to_item(s: Signal) -> MailItemOut:
    labels = set(s.payload.get("label_ids", []))
    return MailItemOut(
        id=s.id,
        subject=s.payload.get("subject", "(no subject)"),
        sender=s.payload.get("from", "unknown"),
        to=s.payload.get("to"),
        occurred_at=s.occurred_at,
        is_starred="STARRED" in labels,
        is_important="IMPORTANT" in labels,
        is_unread="UNREAD" in labels,
        is_spam="SPAM" in labels,
    )
