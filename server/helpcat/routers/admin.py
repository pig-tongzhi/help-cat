"""后台用户与角色。"""

from ..auth import require_admin, require_super_admin
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import (AuditLog, Cat, Community, FeedingLog, FeedingPoint, FeedingShift,
                       LeadMessage, LoginAttempt, PageView, Session as AuthSession, User)
from ..pagination import paginated_items
from ..schemas import RoleUpdate
from ..serializers import audit, user_payload
from fastapi import APIRouter
from ..domain import shanghai_today
from datetime import datetime, timedelta, timezone
from fastapi import Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from typing import Optional
from zoneinfo import ZoneInfo


router = APIRouter()


@router.get("/api/v1/admin/users")
def list_admin_users(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_super_admin(actor)
    items, next_cursor = paginated_items(db, select(User), User, cursor, limit)
    return {"items": [user_payload(item) for item in items], "next_cursor": next_cursor}


@router.post("/api/v1/admin/users/{user_id}/role")
def update_user_role(user_id: str, payload: RoleUpdate, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_super_admin(actor)
    user = db.get(User, user_id)
    if not user:
        error(404, "user_not_found")
    if user.role == "SUPER_ADMIN":
        error(409, "super_admin_immutable")
    if user.role != payload.role:
        before = {"role": user.role}
        user.role = payload.role
        audit(db, actor[0], "ROLE_CHANGE", "user", user.id, before, {"role": user.role})
        db.commit()
    return user_payload(user)


def _days_since(moment, now):
    if moment is None:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (now - moment).days)


@router.get("/api/v1/admin/dashboard")
def admin_dashboard(actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    """后台看板：**今天的状态 → 本周趋势 → 系统与安全**。

    刻意不放累计数字（那是给访客看的），后台要看的是"今天有没有人管、积压多久、
    这周有没有人在动"。全部从现有表算，不新增统计任务。
    """
    require_admin(actor)
    now = datetime.now(timezone.utc)
    today = shanghai_today()
    week_start = (datetime.fromisoformat(today).date() - timedelta(days=6)).isoformat()
    week_since = datetime.combine(datetime.fromisoformat(week_start).date(), datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))

    # ---- 今天：喂食点覆盖率 ----
    points = db.scalars(select(FeedingPoint).where(
        FeedingPoint.is_qa.is_(False), FeedingPoint.status == "ACTIVE")).all()
    covered = set(db.scalars(select(FeedingShift.point_id).where(
        FeedingShift.is_qa.is_(False), FeedingShift.shift_date == today,
        FeedingShift.status != "CANCELLED")).all())
    covered |= set(db.scalars(select(FeedingLog.point_id).where(
        FeedingLog.is_qa.is_(False), FeedingLog.fed_on == today)).all())
    uncovered = [item for item in points if item.id not in covered]

    # 未来 7 天缺口：每天"有认领的点"数，缺的排前面
    horizon_end = (datetime.fromisoformat(today).date() + timedelta(days=7)).isoformat()
    claimed_rows = db.execute(select(FeedingShift.shift_date, FeedingShift.point_id).where(
        FeedingShift.is_qa.is_(False), FeedingShift.status != "CANCELLED",
        FeedingShift.shift_date > today, FeedingShift.shift_date <= horizon_end,
    )).all()
    claimed_by_day = {}
    for day, point_id in claimed_rows:
        claimed_by_day.setdefault(day, set()).add(point_id)
    gaps = []
    for offset in range(1, 8):
        day = (datetime.fromisoformat(today).date() + timedelta(days=offset)).isoformat()
        missing = len(points) - len(claimed_by_day.get(day, set()))
        if missing > 0:
            gaps.append({"day": day, "missing": missing})

    # ---- 今天：积压 ----
    pending_cats = db.scalar(select(func.count()).select_from(Cat).where(
        Cat.is_qa.is_(False), Cat.review_status == "PENDING_REVIEW")) or 0
    pending_communities = db.scalar(select(func.count()).select_from(Community).where(
        Community.is_qa.is_(False), Community.status.in_(("PENDING_REVIEW", "NEEDS_CHANGES")))) or 0
    oldest_pending = max([
        _days_since(value, now) for value in db.scalars(select(Cat.created_at).where(
            Cat.is_qa.is_(False), Cat.review_status == "PENDING_REVIEW")).all()
    ] + [
        _days_since(value, now) for value in db.scalars(select(Community.created_at).where(
            Community.is_qa.is_(False), Community.status.in_(("PENDING_REVIEW", "NEEDS_CHANGES")))).all()
    ] + [0])
    new_leads = db.scalar(select(func.count()).select_from(LeadMessage).where(LeadMessage.status == "NEW")) or 0
    oldest_lead = max([
        _days_since(value, now) for value in db.scalars(select(LeadMessage.created_at).where(
            LeadMessage.status == "NEW")).all()
    ] + [0])
    # 只看已通过、已公开的档案：待审的本来就还没照片，算进来会虚高
    cats_without_photo = db.scalar(select(func.count()).select_from(Cat).where(
        Cat.is_qa.is_(False), Cat.photo_asset_id.is_(None),
        Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE")) or 0

    # ---- 本周趋势 ----
    pv_rows = db.execute(select(PageView.kind, func.sum(PageView.count)).where(
        PageView.day >= week_start).group_by(PageView.kind)).all()
    pv = {kind: int(total or 0) for kind, total in pv_rows}
    leads_week = db.scalar(select(func.count()).select_from(LeadMessage).where(
        LeadMessage.created_at >= week_since)) or 0
    feedings_week = db.scalar(select(func.count()).select_from(FeedingLog).where(
        FeedingLog.is_qa.is_(False), FeedingLog.fed_on >= week_start)) or 0
    volunteer_rows = db.execute(select(FeedingLog.user_id, func.count()).where(
        FeedingLog.is_qa.is_(False), FeedingLog.fed_on >= week_start).group_by(FeedingLog.user_id)).all()
    active_volunteers = len(volunteer_rows)
    top_share = 0
    if feedings_week and volunteer_rows:
        top_share = round(100 * max(int(total) for _, total in volunteer_rows) / feedings_week)
    new_cats_week = db.scalar(select(func.count()).select_from(Cat).where(
        Cat.is_qa.is_(False), Cat.created_at >= week_since,
        Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE")) or 0
    new_users_week = db.scalar(select(func.count()).select_from(User).where(User.created_at >= week_since)) or 0
    users_total = db.scalar(select(func.count()).select_from(User)) or 0
    admins_total = db.scalar(select(func.count()).select_from(User).where(
        User.role.in_(("ADMIN", "SUPER_ADMIN")))) or 0
    recent_users = [
        {"username": item.username or item.nickname or "微信用户", "role": item.role,
         "created_at": item.created_at.isoformat()}
        for item in db.scalars(select(User).order_by(User.created_at.desc()).limit(5)).all()
    ]

    # ---- 设备与安全 ----
    live_sessions = db.scalars(select(AuthSession).where(
        AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)).all()
    audited = set(db.scalars(select(AuditLog.entity_id).where(AuditLog.action == "SESSION_ISSUE")).all())
    login_failures = db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.succeeded.is_(False), LoginAttempt.created_at >= now - timedelta(days=7))) or 0
    active_task_count = db.scalar(select(func.count()).select_from(FeedingShift).where(
        FeedingShift.is_qa.is_(False), FeedingShift.status == "CLAIMED")) or 0

    return {
        "today": {
            "date": today,
            "feeding_points": len(points),
            "covered": len(points) - len(uncovered),
            "coverage_percent": round(100 * (len(points) - len(uncovered)) / len(points)) if points else None,
            "uncovered": [item.name for item in uncovered[:5]],
            "gaps": gaps,
            "pending_cats": pending_cats,
            "pending_communities": pending_communities,
            "oldest_pending_days": oldest_pending,
            "new_leads": new_leads,
            "oldest_lead_days": oldest_lead,
            "cats_without_photo": cats_without_photo,
        },
        "week": {
            "since": week_start,
            "page_views": {"home": pv.get("home", 0), "story": pv.get("story", 0), "welcome": pv.get("welcome", 0),
                           "total": sum(pv.values())},
            "leads": leads_week,
            "lead_conversion_percent": round(100 * leads_week / pv["welcome"]) if pv.get("welcome") else None,
            "feeding_checkins": feedings_week,
            "active_volunteers": active_volunteers,
            "top_volunteer_share_percent": top_share,
            "new_cats": new_cats_week,
            "new_users": new_users_week,
            "claimed_shifts": active_task_count,
        },
        "accounts": {"total": users_total, "admins": admins_total, "recent": recent_users},
        "devices": {
            "active": len(live_sessions),
            "legacy": len([item for item in live_sessions if item.token[:8] not in audited]),
        },
        "security": {"login_failures_7d": login_failures},
    }
