"""定点投喂：喂猫点、打卡与排班。"""

from ..auth import require_admin
from ..dependencies import get_current_user, get_db, get_optional_user
from ..domain import FEEDING_SHIFT_LOOKAHEAD_DAYS, FEEDING_SHIFT_MAX_DAYS, FEEDING_STREAK_MILESTONES, feeding_point_today_sort_key, haversine_distance_m, parse_shift_date, shanghai_today
from ..errors import error
from ..models import Community, FeedingLog, FeedingPoint, FeedingShift, MediaAsset, User
from ..pagination import paginated_items
from ..schemas import FeedingLogCreate, FeedingPointCreate, FeedingPointEdit, FeedingShiftClaim
from ..serializers import audit, community_names, feeding_log_payload, feeding_point_payload, feeding_shift_payload, iso_utc, public_user_label
from datetime import date, datetime, timedelta
from fastapi import APIRouter
from fastapi import Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from typing import Optional
from zoneinfo import ZoneInfo


router = APIRouter()


@router.get("/api/v1/public/feeding-stats")
def public_feeding_stats(db: DbSession = Depends(get_db)):
    today = shanghai_today()
    week_start = (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=6)).isoformat()
    live = (FeedingLog.is_qa.is_(False),)
    points_active = db.scalar(select(func.count()).select_from(FeedingPoint).where(
        FeedingPoint.is_qa.is_(False), FeedingPoint.status == "ACTIVE",
    )) or 0
    feeds_today = db.scalar(select(func.count()).select_from(FeedingLog).where(*live, FeedingLog.fed_on == today)) or 0
    feeds_week = db.scalar(select(func.count()).select_from(FeedingLog).where(*live, FeedingLog.fed_on >= week_start)) or 0
    volunteers_week = db.scalar(select(func.count(func.distinct(FeedingLog.user_id))).where(*live, FeedingLog.fed_on >= week_start)) or 0
    last_fed_at = db.scalar(select(func.max(FeedingLog.fed_at)).where(*live))
    return {
        "points_active": points_active, "feeds_today": feeds_today, "feeds_week": feeds_week,
        "volunteers_week": volunteers_week, "last_fed_at": iso_utc(last_fed_at), "today": today,
    }


@router.get("/api/v1/feeding-points")
def list_feeding_points(
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    lat: Optional[float] = Query(default=None, ge=-90, le=90),
    lng: Optional[float] = Query(default=None, ge=-180, le=180),
    sort: Optional[str] = None,
    actor=Depends(get_optional_user),
    db: DbSession = Depends(get_db),
):
    stmt = select(FeedingPoint).where(FeedingPoint.is_qa.is_(False), FeedingPoint.status == "ACTIVE")
    today = shanghai_today()
    distance_mode = lat is not None and lng is not None
    ordered = distance_mode or sort == "today" or lat is not None or lng is not None or sort is not None
    # Distance and "today" orderings are computed in Python, and a bare lat/lng/sort
    # still opts out of the created_at cursor order, so the cursor is ignored here
    # and the response always reports next_cursor = None.
    if ordered:
        items, next_cursor = list(db.scalars(stmt).all()), None
    else:
        items, next_cursor = paginated_items(db, stmt, FeedingPoint, cursor, limit)
    ids = [item.id for item in items]
    counts, lasts, mine = {}, {}, set()
    if ids:
        counts = dict(db.execute(
            select(FeedingLog.point_id, func.count()).where(
                FeedingLog.is_qa.is_(False), FeedingLog.fed_on == today, FeedingLog.point_id.in_(ids),
            ).group_by(FeedingLog.point_id)
        ).all())
        lasts = dict(db.execute(
            select(FeedingLog.point_id, func.max(FeedingLog.fed_at)).where(
                FeedingLog.is_qa.is_(False), FeedingLog.point_id.in_(ids),
            ).group_by(FeedingLog.point_id)
        ).all())
        if actor:
            mine = {row[0] for row in db.execute(
                select(FeedingLog.point_id).where(
                    FeedingLog.is_qa.is_(False), FeedingLog.fed_on == today,
                    FeedingLog.point_id.in_(ids), FeedingLog.user_id == actor[0],
                )
            ).all()}
    distances = {}
    if distance_mode:
        # Points without coordinates keep distance_m = None and sort after the located ones.
        located = [item for item in items if item.latitude is not None and item.longitude is not None]
        unlocated = [item for item in items if item.latitude is None or item.longitude is None]
        for item in located:
            distances[item.id] = round(haversine_distance_m(lat, lng, item.latitude, item.longitude))
        located.sort(key=lambda item: (distances[item.id], item.name))
        items = located + unlocated
    elif sort == "today":
        items.sort(key=lambda item: feeding_point_today_sort_key(item, counts.get(item.id, 0), lasts.get(item.id)))
    elif ordered:
        items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    if ordered:
        items = items[:limit]
    names = community_names(db, [item.community_id for item in items])
    return {
        "items": [
            feeding_point_payload(
                item, counts.get(item.id, 0), item.id in mine, lasts.get(item.id),
                names.get(item.community_id, ""), distances.get(item.id),
            )
            for item in items
        ],
        "next_cursor": next_cursor,
    }


@router.post("/api/v1/feeding-points/{point_id}/logs", status_code=201)
def create_feeding_log(
    point_id: str,
    payload: FeedingLogCreate,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    """Check in at a feeding point. One check-in per volunteer per point per day."""
    point = db.get(FeedingPoint, point_id)
    if not point or point.status != "ACTIVE":
        error(404, "feeding_point_not_found")
    if payload.photo_asset_id:
        asset = db.get(MediaAsset, payload.photo_asset_id)
        if not asset or asset.created_by != actor[0]:
            error(403, "photo_asset_forbidden")
    today = shanghai_today()
    existing = db.scalar(select(FeedingLog).where(
        FeedingLog.point_id == point.id, FeedingLog.user_id == actor[0], FeedingLog.fed_on == today,
    ))
    if existing:
        # Same volunteer, same point, same day: report the original check-in.
        return feeding_log_payload(existing, point.name)
    item = FeedingLog(
        point_id=point.id, user_id=actor[0], fed_on=today, food_note=payload.food_note,
        note=payload.note, photo_asset_id=payload.photo_asset_id, is_qa=False,
    )
    db.add(item)
    db.flush()
    audit(db, actor[0], "FEED", "feeding_point", point.id, after={"fed_on": today, "log_id": item.id})
    db.commit()
    try:
        # A volunteer who claimed today's slot has just carried it out; a
        # failure here must never turn a valid check-in into an error.
        shift = db.scalar(select(FeedingShift).where(
            FeedingShift.point_id == point.id, FeedingShift.user_id == actor[0],
            FeedingShift.shift_date == today, FeedingShift.status == "CLAIMED",
        ))
        if shift:
            shift.status = "DONE"
            db.commit()
    except Exception:
        db.rollback()
    return feeding_log_payload(item, point.name)


@router.get("/api/v1/feeding-logs/mine")
def list_my_feeding_logs(
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    stmt = select(FeedingLog).where(FeedingLog.is_qa.is_(False), FeedingLog.user_id == actor[0])
    items, next_cursor = paginated_items(db, stmt, FeedingLog, cursor, limit)
    point_names = {}
    if items:
        point_names = dict(db.execute(
            select(FeedingPoint.id, FeedingPoint.name).where(FeedingPoint.id.in_({item.point_id for item in items}))
        ).all())
    return {
        "items": [feeding_log_payload(item, point_names.get(item.point_id, "")) for item in items],
        "next_cursor": next_cursor,
    }


@router.get("/api/v1/feeding-logs/mine/summary")
def my_feeding_summary(actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    """This volunteer's own check-in progress on the Asia/Shanghai calendar."""
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    rows = db.scalars(select(FeedingLog.fed_on).where(
        FeedingLog.is_qa.is_(False), FeedingLog.user_id == actor[0],
    ).distinct()).all()
    days = set()
    for value in rows:
        try:
            days.add(datetime.fromisoformat(value).date())
        except (TypeError, ValueError):
            continue
    checked_in_today = today in days
    # A streak only breaks once a whole day is missed, so an un-fed today still
    # counts backwards from yesterday.
    streak_days = 0
    cursor_day = today if checked_in_today else today - timedelta(days=1)
    while cursor_day in days:
        streak_days += 1
        cursor_day -= timedelta(days=1)
    week_start = today - timedelta(days=6)
    points_checked_today = db.scalar(select(func.count()).select_from(FeedingLog).where(
        FeedingLog.is_qa.is_(False), FeedingLog.user_id == actor[0], FeedingLog.fed_on == today.isoformat(),
    )) or 0
    return {
        "checked_in_today": checked_in_today,
        "streak_days": streak_days,
        "days_this_week": sum(1 for day in days if week_start <= day <= today),
        "total_days": len(days),
        "last_fed_on": max(days).isoformat() if days else None,
        "next_milestone": next((value for value in FEEDING_STREAK_MILESTONES if value > streak_days), None),
        "points_checked_today": points_checked_today,
    }

# ---- 排班认领 ------------------------------------------------------


@router.get("/api/v1/feeding-shifts")
def list_feeding_shifts(
    from_: Optional[str] = Query(default=None, alias="from"),
    days: int = Query(default=7, ge=1, le=FEEDING_SHIFT_MAX_DAYS),
    actor=Depends(get_optional_user),
    db: DbSession = Depends(get_db),
):
    """The public feeding schedule: which volunteer owns which point and day."""
    start = parse_shift_date(from_) if from_ else date.fromisoformat(shanghai_today())
    end = start + timedelta(days=days - 1)
    rows = db.scalars(
        select(FeedingShift)
        .join(FeedingPoint, FeedingShift.point_id == FeedingPoint.id)
        .where(
            FeedingShift.is_qa.is_(False), FeedingPoint.is_qa.is_(False),
            FeedingPoint.status == "ACTIVE",
            # Cancelled rows are history: the slot is free again and must not
            # keep the public grid showing the day as taken.
            FeedingShift.status != "CANCELLED",
            FeedingShift.shift_date >= start.isoformat(),
            FeedingShift.shift_date <= end.isoformat(),
        )
        .order_by(FeedingShift.shift_date.asc(), FeedingPoint.name.asc())
    ).all()
    point_names, labels = {}, {}
    if rows:
        point_names = dict(db.execute(
            select(FeedingPoint.id, FeedingPoint.name).where(FeedingPoint.id.in_({item.point_id for item in rows}))
        ).all())
        for user in db.scalars(select(User).where(User.id.in_({item.user_id for item in rows}))):
            labels[user.id] = public_user_label(user)
    return {
        "from": start.isoformat(), "days": days, "today": shanghai_today(),
        "items": [
            feeding_shift_payload(
                item, point_names.get(item.point_id, ""), labels.get(item.user_id, ""),
                bool(actor and item.user_id == actor[0]),
            )
            for item in rows
        ],
    }


@router.post("/api/v1/feeding-points/{point_id}/shifts", status_code=201)
def claim_feeding_shift(
    point_id: str,
    payload: FeedingShiftClaim,
    response: Response,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    """Claim the feeding duty for one point on one day."""
    today = date.fromisoformat(shanghai_today())
    shift_date = parse_shift_date(payload.shift_date)
    if not today <= shift_date <= today + timedelta(days=FEEDING_SHIFT_LOOKAHEAD_DAYS):
        error(422, "shift_date_out_of_range")
    point = db.get(FeedingPoint, point_id)
    if not point or point.status != "ACTIVE":
        error(404, "feeding_point_not_found")
    label = public_user_label(db.get(User, actor[0]))
    existing = db.scalar(select(FeedingShift).where(
        FeedingShift.point_id == point.id, FeedingShift.shift_date == payload.shift_date,
        FeedingShift.status != "CANCELLED",
    ))
    if existing:
        if existing.user_id == actor[0]:
            # Re-claiming your own live slot reports the original claim.
            response.status_code = 200
            return feeding_shift_payload(existing, point.name, label, True)
        error(409, "shift_already_claimed")
    item = FeedingShift(
        point_id=point.id, user_id=actor[0], shift_date=payload.shift_date,
        status="CLAIMED", note=payload.note, is_qa=False,
    )
    db.add(item)
    db.flush()
    audit(db, actor[0], "CREATE", "feeding_shift", item.id, after={
        "point_id": item.point_id, "shift_date": item.shift_date, "status": item.status,
    })
    db.commit()
    return feeding_shift_payload(item, point.name, label, True)


@router.post("/api/v1/feeding-shifts/{shift_id}/release")
def release_feeding_shift(shift_id: str, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    """The claimer, or an admin acting for them, gives the day back."""
    item = db.get(FeedingShift, shift_id)
    if not item:
        error(404, "feeding_shift_not_found")
    if item.status == "CANCELLED":
        error(409, "shift_already_cancelled")
    is_admin = actor[1] in {"ADMIN", "SUPER_ADMIN"}
    if item.user_id != actor[0] and not is_admin:
        error(403, "forbidden")
    if item.status == "DONE" and not is_admin:
        error(403, "shift_done_locked")
    before = {"status": item.status}
    item.status = "CANCELLED"
    audit(db, actor[0], "UPDATE", "feeding_shift", item.id, before=before, after={"status": item.status})
    db.commit()
    point = db.get(FeedingPoint, item.point_id)
    return feeding_shift_payload(
        item, point.name if point else "", public_user_label(db.get(User, item.user_id)),
        item.user_id == actor[0],
    )


@router.get("/api/v1/feeding-shifts/mine")
def list_my_feeding_shifts(
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    """This volunteer's upcoming claims.

    `paginated_items` pages by created_at desc, id desc; a later claim may
    cover an earlier date, so creation order is the accepted page order.
    """
    today = shanghai_today()
    stmt = select(FeedingShift).where(
        FeedingShift.is_qa.is_(False), FeedingShift.user_id == actor[0],
        FeedingShift.shift_date >= today,
    )
    items, next_cursor = paginated_items(db, stmt, FeedingShift, cursor, limit)
    point_names = {}
    if items:
        point_names = dict(db.execute(
            select(FeedingPoint.id, FeedingPoint.name).where(FeedingPoint.id.in_({item.point_id for item in items}))
        ).all())
    label = public_user_label(db.get(User, actor[0]))
    return {
        "items": [
            feeding_shift_payload(item, point_names.get(item.point_id, ""), label, True)
            for item in items
        ],
        "next_cursor": next_cursor,
    }


@router.post("/api/v1/admin/feeding-points", status_code=201)
def create_feeding_point(payload: FeedingPointCreate, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    if payload.community_id:
        community = db.get(Community, payload.community_id)
        if not community or community.status != "ACTIVE":
            error(404, "community_not_found")
    item = FeedingPoint(
        name=payload.name.strip(), community_id=payload.community_id, location_note=payload.location_note,
        feeding_time=payload.feeding_time, caretaker_note=payload.caretaker_note,
        latitude=payload.latitude, longitude=payload.longitude, created_by=actor[0], is_qa=False,
    )
    db.add(item)
    db.flush()
    audit(db, actor[0], "CREATE", "feeding_point", item.id, after={"name": item.name})
    db.commit()
    return feeding_point_payload(
        item, community_name=community_names(db, [item.community_id]).get(item.community_id, ""),
    )


@router.patch("/api/v1/admin/feeding-points/{point_id}")
def edit_feeding_point(
    point_id: str,
    payload: FeedingPointEdit,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    require_admin(actor)
    item = db.get(FeedingPoint, point_id)
    if not item:
        error(404, "feeding_point_not_found")
    before = {"name": item.name, "status": item.status, "feeding_time": item.feeding_time}
    for field in ("name", "location_note", "feeding_time", "caretaker_note", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value.strip() if field != "status" else value)
    for field in ("latitude", "longitude"):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value)
    audit(db, actor[0], "UPDATE", "feeding_point", item.id, before=before, after={
        "name": item.name, "status": item.status, "feeding_time": item.feeding_time,
    })
    db.commit()
    return feeding_point_payload(item)


@router.get("/api/v1/admin/feeding-points")
def admin_list_feeding_points(
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    require_admin(actor)
    stmt = select(FeedingPoint).where(FeedingPoint.is_qa.is_(False))
    if status:
        stmt = stmt.where(FeedingPoint.status == status)
    items, next_cursor = paginated_items(db, stmt, FeedingPoint, cursor, limit)
    today = shanghai_today()
    ids = [item.id for item in items]
    counts, lasts = {}, {}
    if ids:
        counts = dict(db.execute(
            select(FeedingLog.point_id, func.count()).where(
                FeedingLog.is_qa.is_(False), FeedingLog.fed_on == today, FeedingLog.point_id.in_(ids),
            ).group_by(FeedingLog.point_id)
        ).all())
        lasts = dict(db.execute(
            select(FeedingLog.point_id, func.max(FeedingLog.fed_at)).where(
                FeedingLog.is_qa.is_(False), FeedingLog.point_id.in_(ids),
            ).group_by(FeedingLog.point_id)
        ).all())
    names = community_names(db, [item.community_id for item in items])
    return {
        "items": [
            feeding_point_payload(item, counts.get(item.id, 0), False, lasts.get(item.id), names.get(item.community_id, ""))
            for item in items
        ],
        "next_cursor": next_cursor,
    }

# ---- 猫咪时间线 ----------------------------------------------------
