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
    "microsoft_onedrive": (Provider.MICROSOFT_ONEDRIVE,),  # rail + browse
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


# --- Outlook Calendar read surface ----------------------------------------

@router.get("/microsoft/calendar")
def outlook_calendar(
    days: int = 30,
    q: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """The agenda as Sentinel has it, plus the overlaps computed here rather
    than in the browser - the same deterministic rule the advisor uses, so the
    page and the assistant can never disagree about what conflicts."""
    from datetime import datetime, timedelta, timezone

    conns = _connections(session, workspace_id, user.id, (Provider.MICROSOFT_OUTLOOK_CALENDAR,))
    if not conns:
        raise HTTPException(status_code=404, detail="Outlook Calendar is not connected")

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=max(1, min(days, 90)))
    rows = session.execute(
        select(Signal)
        .where(
            Signal.connection_id.in_([c.id for c in conns]),
            Signal.type == SignalType.CALENDAR_EVENT,
            Signal.occurred_at >= now - timedelta(days=1),
            Signal.occurred_at <= horizon,
        )
        .order_by(Signal.occurred_at.asc())
    ).scalars().all()

    def _parse(raw):
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    events = []
    for s in rows:
        p = s.payload or {}
        start = _parse(p.get("start")) or s.occurred_at
        if q and q.lower() not in (p.get("title") or "").lower():
            continue
        events.append({
            "id": str(s.id),
            "event_id": s.external_id,
            "title": p.get("title") or "(no title)",
            "start": start.isoformat() if start else None,
            "end": (_parse(p.get("end")) or start).isoformat() if start else None,
            "attendee_count": int(p.get("attendee_count") or 0),
            "attendee_emails": p.get("attendee_emails") or [],
            "organizer": p.get("organizer"),
            "has_meeting_link": bool(p.get("has_meeting_link")),
            "meet_url": p.get("meet_url"),
            "status": p.get("status") or "confirmed",
            "url": p.get("url"),
            "day": start.date().isoformat() if start else None,
        })

    # Overlaps, computed once here. Reported per pair, newest-first ordering
    # preserved from the query.
    conflicts = []
    dated = [e for e in events if e["start"] and e["end"]]
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            if b["start"] >= a["end"]:
                break
            conflicts.append({"a": a["title"], "b": b["title"], "when": a["start"]})

    return {"events": events, "conflicts": conflicts, "account": conns[0].org}


# --- Microsoft To Do read surface -----------------------------------------

@router.get("/microsoft/todo")
def microsoft_todo(
    q: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Tasks read LIVE from Graph, unlike mail and calendar which are served
    from ingested signals.

    The difference is deliberate. A task list is small, and a workspace where
    the task you just added does not appear until the next poll is broken. The
    ingested TASK signals still exist and still feed the Intelligence Core on
    their own schedule - this endpoint is the working view, not a second
    source of truth.
    """
    from datetime import datetime, timedelta, timezone

    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    conns = _connections(session, workspace_id, user.id, (Provider.MICROSOFT_TODO,))
    if not conns:
        raise HTTPException(status_code=404, detail="Microsoft To Do is not connected")

    now = datetime.now(timezone.utc)
    today = now.date()
    try:
        with GraphClient(get_valid_access_token(session, conns[0])) as client:
            lists = client.task_lists()
            tasks: list[dict] = []
            for lst in lists:
                for raw in client._paginate(f"/me/todo/lists/{lst['id']}/tasks", {"$top": "50"}, 200):
                    tasks.append(client._task_out(raw, lst["id"], lst["name"]))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Couldn't reach Microsoft To Do just now") from exc

    out = []
    for t in tasks:
        if q and q.lower() not in t["title"].lower():
            continue
        due = t["due_at"]
        # The bucket a task belongs to, computed once here so the page and the
        # detectors agree on what "overdue" and "today" mean.
        if t["completed"]:
            bucket = "completed"
        elif due is None:
            bucket = "someday"
        elif due.date() < today:
            bucket = "overdue"
        elif due.date() == today:
            bucket = "today"
        else:
            bucket = "upcoming"
        out.append({
            "id": t["id"], "list_id": t["list_id"], "list": t["list"],
            "title": t["title"], "notes": t["body"],
            "completed": t["completed"], "importance": t["importance"],
            "due_at": due.isoformat() if due else None,
            "bucket": bucket,
        })

    out.sort(key=lambda t: (t["due_at"] or "9999", t["title"].lower()))
    counts = {b: sum(1 for t in out if t["bucket"] == b) for b in ("overdue", "today", "upcoming", "someday", "completed")}
    return {"tasks": out, "lists": lists, "counts": counts, "account": conns[0].org}


# --- OneDrive read surface -------------------------------------------------

def _graph_for(session: Session, workspace_id, user_id, provider: Provider, label: str):
    from app.integrations.graph_client import GraphClient
    from app.integrations.microsoft_auth import get_valid_access_token

    conns = _connections(session, workspace_id, user_id, (provider,))
    if not conns:
        raise HTTPException(status_code=404, detail=f"{label} is not connected")
    return GraphClient(get_valid_access_token(session, conns[0])), conns[0]


@router.get("/microsoft/onedrive")
def onedrive_browse(
    folder_id: str | None = None,
    q: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Browse a folder, or search the whole drive. Read live from Graph: a file
    browser whose contents lag behind what you just created is not a browser."""
    client, conn = _graph_for(session, workspace_id, user.id, Provider.MICROSOFT_ONEDRIVE, "OneDrive")
    try:
        with client:
            items = client.search_drive(q) if q else client.list_children(folder_id)
            current = client.get_item(folder_id) if folder_id else None
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Couldn't reach OneDrive just now") from exc

    def out(i):
        return {
            "id": i["id"], "name": i["name"], "is_folder": i["is_folder"],
            "child_count": i["child_count"], "size": i["size"], "mime_type": i["mime_type"],
            "modified_at": i["modified_at"].isoformat() if i["modified_at"] else None,
            "modified_by": i["modified_by"], "shared": i["shared"],
            "parent_id": i["parent_id"], "url": i["url"],
        }

    return {
        "items": [out(i) for i in items],
        "folder": out(current) if current else None,
        "searching": bool(q),
        "account": conn.org,
    }


# --- OneNote read surface --------------------------------------------------

@router.get("/microsoft/onenote")
def onenote_browse(
    notebook_id: str | None = None,
    section_id: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Notebooks -> sections -> pages, resolved one level at a time so a large
    notebook is never fetched wholesale."""
    client, conn = _graph_for(session, workspace_id, user.id, Provider.MICROSOFT_ONENOTE, "OneNote")
    try:
        with client:
            notebooks = client.notebooks()
            sections = client.sections(notebook_id) if notebook_id else []
            pages = client.pages(section_id) if section_id else []
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Couldn't reach OneNote just now") from exc

    return {
        "notebooks": notebooks,
        "sections": sections,
        "pages": [
            {"id": p["id"], "title": p["title"],
             "modified_at": p["modified_at"].isoformat() if p["modified_at"] else None,
             "url": p["url"]}
            for p in pages
        ],
        "account": conn.org,
    }


@router.get("/microsoft/onenote/pages/{page_id}")
def onenote_page(
    page_id: str,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """A page's text, fetched live and never stored - the same rule as a mail
    body. Sentinel keeps metadata; content stays with the system of record."""
    from app.services.conversation_signals import strip_html

    client, _ = _graph_for(session, workspace_id, user.id, Provider.MICROSOFT_ONENOTE, "OneNote")
    try:
        with client:
            html = client.page_content(page_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Couldn't open that page just now") from exc
    return {"page_id": page_id, "text": strip_html(html)}
