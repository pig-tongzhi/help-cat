"""公益成果台账与公开总数。"""

from ..auth import require_admin
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import ImpactEvent
from ..pagination import paginated_items
from ..schemas import ImpactEventCreate
from ..serializers import audit, impact_event_payload
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi import Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from typing import Optional


router = APIRouter()


@router.get("/api/v1/public/metrics")
def public_metrics(db: DbSession = Depends(get_db)):
    values = dict(db.execute(
        select(ImpactEvent.kind, func.sum(ImpactEvent.amount)).where(
            ImpactEvent.is_qa.is_(False), ImpactEvent.reversed_at.is_(None),
        ).group_by(ImpactEvent.kind)
    ).all())
    return {
        "rescued": values.get("RESCUED", 0),
        "adopted": values.get("ADOPTED", 0),
        "medical": values.get("MEDICAL", 0),
        "supporters": values.get("SUPPORTER", 0),
    }


@router.post("/api/v1/admin/impact-events", status_code=201)
def create_impact_event(payload: ImpactEventCreate, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    event = ImpactEvent(
        kind=payload.kind, amount=payload.amount, note=payload.note.strip(),
        occurred_at=payload.occurred_at or datetime.now(timezone.utc), created_by=actor[0], is_qa=False,
    )
    db.add(event)
    db.flush()
    audit(db, actor[0], "IMPACT_EVENT_CREATE", "impact_event", event.id, after={
        "kind": event.kind, "amount": event.amount, "occurred_at": event.occurred_at.isoformat(),
    })
    db.commit()
    return impact_event_payload(event)


@router.get("/api/v1/admin/impact-events")
def list_impact_events(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    items, next_cursor = paginated_items(db, select(ImpactEvent), ImpactEvent, cursor, limit)
    return {"items": [impact_event_payload(item) for item in items], "next_cursor": next_cursor}


@router.post("/api/v1/admin/impact-events/{event_id}/reverse")
def reverse_impact_event(event_id: str, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    event = db.get(ImpactEvent, event_id)
    if not event:
        error(404, "impact_event_not_found")
    if event.reversed_at is None:
        event.reversed_at = datetime.now(timezone.utc)
        event.reversed_by = actor[0]
        audit(db, actor[0], "IMPACT_EVENT_REVERSE", "impact_event", event.id, before={
            "reversed_at": None,
        }, after={"reversed_at": event.reversed_at.isoformat()})
        db.commit()
    return impact_event_payload(event)
