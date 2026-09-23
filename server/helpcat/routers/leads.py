"""欢迎页留言（线索）。"""

from ..auth import require_admin
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import LeadMessage
from ..pagination import paginated_items
from ..schemas import LeadMessageCreate, LeadMessageStatusUpdate
from ..serializers import audit, lead_message_payload
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from fastapi import Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from typing import Optional


router = APIRouter()

# 访客不给称呼时用的默认名。放在后端而不是只放前端：欢迎页、小程序、直接调接口
# 的客户端都得到同一个结果，不会出现一半是空名字的留言。
DEFAULT_LEAD_NAME = "喜猫人"


@router.get("/api/v1/public/contact")
def public_contact(request: Request):
    """How a visitor reaches the operator.

    Public by design: the welcome page only renders it after the visitor
    taps "查看管理员联系方式", which is a UI affordance rather than a secret.
    """
    return {
        "wechat": request.app.state.settings.admin_wechat,
        "wechat_note": request.app.state.settings.admin_wechat_note,
        "phone": request.app.state.settings.admin_phone,
        "qr_image": request.app.state.settings.admin_qr_image,
        "note": request.app.state.settings.admin_contact_note,
    }


@router.post("/api/v1/public/messages", status_code=201)
def create_lead_message(payload: LeadMessageCreate, request: Request, db: DbSession = Depends(get_db)):
    """Accept a contact left by a visitor with no account."""
    client_ip = request.client.host if request.client else ""
    now = datetime.now(timezone.utc)
    if client_ip:
        recent = db.scalar(select(func.count()).select_from(LeadMessage).where(
            LeadMessage.client_ip == client_ip,
            LeadMessage.created_at >= now - timedelta(hours=1),
        )) or 0
        if recent >= request.app.state.settings.lead_rate_limit_per_hour:
            error(429, "too_many_messages")
    duplicate = db.scalar(select(LeadMessage).where(
        LeadMessage.contact == payload.contact,
        LeadMessage.created_at >= now - timedelta(minutes=request.app.state.settings.lead_dedupe_minutes),
    ).order_by(LeadMessage.created_at.desc()))
    if duplicate:
        # The same contact again is the same lead, not a new one.
        return lead_message_payload(duplicate)
    item = LeadMessage(
        name=payload.name or DEFAULT_LEAD_NAME,
        contact_type=payload.contact_type,
        contact=payload.contact,
        message=payload.message,
        source=payload.source,
        client_ip=client_ip,
        is_qa=False,
    )
    db.add(item)
    db.commit()
    return lead_message_payload(item)


@router.get("/api/v1/admin/messages")
def list_lead_messages(
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    require_admin(actor)
    stmt = select(LeadMessage).where(LeadMessage.is_qa.is_(False))
    if status:
        stmt = stmt.where(LeadMessage.status == status)
    items, next_cursor = paginated_items(db, stmt, LeadMessage, cursor, limit)
    new_count = db.scalar(select(func.count()).select_from(LeadMessage).where(
        LeadMessage.is_qa.is_(False), LeadMessage.status == "NEW",
    )) or 0
    return {
        "items": [lead_message_payload(item) for item in items],
        "next_cursor": next_cursor,
        "new_count": new_count,
    }


@router.post("/api/v1/admin/messages/{message_id}/status")
def update_lead_message_status(
    message_id: str,
    payload: LeadMessageStatusUpdate,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    require_admin(actor)
    item = db.get(LeadMessage, message_id)
    if not item:
        error(404, "lead_message_not_found")
    before = {"status": item.status, "admin_note": item.admin_note}
    item.status = payload.status
    if payload.note:
        item.admin_note = payload.note
    item.handled_by = actor[0]
    item.handled_at = datetime.now(timezone.utc)
    audit(db, actor[0], "LEAD_MESSAGE_STATUS", "lead_message", item.id, before=before, after={
        "status": item.status, "admin_note": item.admin_note,
    })
    db.commit()
    return lead_message_payload(item)
