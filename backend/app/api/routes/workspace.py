"""The Provider Workspace API - the read side of "work inside Sentinel".

Two kinds of endpoint live here:

  /workspace/{service}/intelligence   provider-AGNOSTIC. Findings, situations
                                      and recommendations narrowed to one
                                      service, so every workspace page gets the
                                      same intelligence rail for free. GitHub,
                                      Slack and Google get it without a line of
                                      new code.

  /workspace/microsoft/mail/...       the Outlook read surface. Reads come from
                                      Sentinel's own ingested signals (fast,
                                      already normalized); only a message BODY
                                      is fetched live, and never stored - the
                                      same posture as the Gmail reader.

There are NO write endpoints here, deliberately. Every write goes through
/actions, which is the Action Registry boundary: allow-listed, validated,
risk-classified, confirmed, verified, audited and undoable. A route here that
called Graph to change something would be a second, unaudited write path.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.domain.finding import FindingSource
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.situation_reasoning import SituationReasoning
from app.models.user import User
from app.services.connection_state import connection_state
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.situation_engine import list_situations

router = APIRouter(prefix="/workspace", tags=["workspace"])

# Which providers back each workspace service. The only place a service name is
# mapped to providers - pages, intelligence and health all read it, so a new
# service is one entry here.
SERVICE_PROVIDERS: dict[str, tuple[Provider, ...]] = {
    "microsoft_mail": (Provider.MICROSOFT_OUTLOOK_MAIL,),
    "microsoft_calendar": (Provider.MICROSOFT_OUTLOOK_CALENDAR,),
    "microsoft_todo": (Provider.MICROSOFT_TODO,),
    "microsoft_onedrive": (Provider.MICROSOFT_ONEDRIVE,),
    "microsoft_onenote": (Provider.MICROSOFT_ONENOTE,),
    "microsoft_teams": (Provider.MICROSOFT_TEAMS,),
    "gmail": (Provider.GMAIL,),
    "google_calendar": (Provider.GOOGLE_CALENDAR,),
    "github": (Provider.GITHUB,),
    "slack": (Provider.SLACK,),
}


def _providers_for(service: str) -> tuple[Provider, ...]:
    providers = SERVICE_PROVIDERS.get(service)
    if providers is None:
        raise HTTPException(status_code=404, detail=f"Unknown workspace service: {service}")
    return providers


def _connections(session: Session, workspace_id, user_id, providers) -> list[Connection]:
    return list(session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user_id,
            Connection.provider.in_(providers),
        )
    ).scalars().all())


@router.get("/{service}/intelligence")
def service_intelligence(
    service: str,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Everything Sentinel knows about ONE service, for its workspace rail.

    Provider-agnostic by construction: it reads the canonical Finding stream and
    the correlated situations, filtering by which providers back this service.
    Nothing here knows what Microsoft or GitHub are.
    """
    providers = _providers_for(service)
    provider_values = {p.value for p in providers}
    scope = personal_scope(session, workspace_id, user.id)

    all_findings = list_findings(session, scope)
    findings = [
        {
            "id": f.id, "title": f.title, "why": f.summary, "tier": f.tier.value,
            "kind": f.kind, "provider": f.provider, "url": f.evidence_url,
        }
        for f in all_findings if f.provider in provider_values
    ]
    mine = {f["id"] for f in findings}

    # A situation earns a place on this service's rail when at least one of its
    # findings belongs to the service - which is exactly how a cross-provider
    # situation surfaces on both of the pages it concerns.
    from app.models.correlated_situation import SituationFinding

    situations = []
    for sit in list_situations(session, workspace_id, scope.key):
        members = session.execute(
            select(SituationFinding).where(SituationFinding.situation_id == sit.id)
        ).scalars().all()
        if not any(m.finding_id in mine for m in members):
            continue
        reasoning = session.execute(
            select(SituationReasoning).where(SituationReasoning.situation_id == sit.id)
        ).scalar_one_or_none()
        situations.append({
            "id": str(sit.id), "title": sit.title, "severity": sit.severity,
            "members": sit.member_count, "cross_provider": sit.cross_provider,
            "explanation": reasoning.explanation if reasoning else None,
            "recommendations": (reasoning.recommended_actions if reasoning else []) or [],
        })

    conns = _connections(session, workspace_id, user.id, providers)
    return {
        "service": service,
        "connected": bool(conns),
        "health": connection_state(conns[0]).value if conns else None,
        "last_synced_at": max((c.last_synced_at for c in conns if c.last_synced_at), default=None),
        "account": conns[0].org if conns else None,
        "findings": findings,
        "situations": situations,
        "critical_count": sum(1 for f in findings if f["tier"] == "critical"),
    }


# --- Outlook Mail read surface --------------------------------------------

@router.get("/microsoft/mail")
def outlook_mail(
    filter: str = "recent",
    q: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """The mailbox as Sentinel has it - served from ingested signals, so the
    list is instant and already carries the normalized flags the rest of the
    product reasons about."""
    conns = _connections(session, workspace_id, user.id, (Provider.MICROSOFT_OUTLOOK_MAIL,))
    if not conns:
        raise HTTPException(status_code=404, detail="Outlook Mail is not connected")

    rows = session.execute(
        select(Signal)
        .where(Signal.connection_id.in_([c.id for c in conns]), Signal.type == SignalType.EMAIL)
        .order_by(Signal.occurred_at.desc())
        .limit(500)
    ).scalars().all()

    out: list[dict] = []
    for s in rows:
        p = s.payload or {}
        labels = set(p.get("label_ids") or [])
        item = {
            "id": str(s.id),
            "message_id": s.external_id,
            "subject": p.get("subject") or "(no subject)",
            "from": p.get("from") or s.actor,
            "to": p.get("to"),
            "occurred_at": s.occurred_at.isoformat() if s.occurred_at else None,
            "unread": "UNREAD" in labels,
            "important": "IMPORTANT" in labels,
            "flagged": "STARRED" in labels,
            "bulk": bool(p.get("is_bulk")),
            "thread_id": p.get("thread_id"),
            "url": p.get("url"),
        }
        if filter == "unread" and not item["unread"]:
            continue
        if filter == "flagged" and not item["flagged"]:
            continue
        if filter == "important" and not item["important"]:
            continue
        if q:
            needle = q.lower()
            if needle not in item["subject"].lower() and needle not in (item["from"] or "").lower():
                continue
        out.append(item)
        if len(out) >= min(limit, 200):
            break
    return out


@router.get("/microsoft/mail/{signal_id}/body")
def outlook_mail_body(
    signal_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """The message body, fetched LIVE from Microsoft and never stored - the
    same rule Gmail follows. Sentinel keeps metadata; content stays with the
    system of record."""
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token
    from app.services.conversation_signals import strip_html

    signal = session.get(Signal, signal_id)
    if signal is None or signal.workspace_id != workspace_id or signal.type != SignalType.EMAIL:
        raise HTTPException(status_code=404, detail="Message not found")
    conns = _connections(session, workspace_id, user.id, (Provider.MICROSOFT_OUTLOOK_MAIL,))
    if not conns:
        raise HTTPException(status_code=404, detail="Outlook Mail is not connected")

    try:
        with GraphClient(get_valid_access_token(session, conns[0])) as client:
            message = client.message(signal.external_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Couldn't reach Outlook just now") from exc

    body = message["body_html"]
    return {
        "message_id": message["id"],
        "subject": message["subject"],
        "from": message["from"],
        "to": message["to"],
        "body_text": strip_html(body) if message["body_type"].lower() == "html" else body,
        "is_read": message["is_read"],
        "flagged": message["flagged"],
        "url": message["url"],
    }
