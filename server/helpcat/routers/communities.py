"""小区治理：候选、审核、纠错、合并。"""

from ..auth import require_admin
from ..community_rules import normalize_community_name
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import Cat, Community
from ..pagination import paginated_items
from ..reviews import approve_community
from ..schemas import CommunityArchive, CommunityCreate, CommunityEdit, CommunityMerge, CommunityReview
from ..serializers import admin_community_payload, audit, community_payload, is_qa_label
from fastapi import APIRouter
from fastapi import Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.exc import StaleDataError
from typing import Optional


router = APIRouter()


@router.get("/api/v1/communities")
def list_communities(q: str = "", cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), db: DbSession = Depends(get_db)):
    items, next_cursor = paginated_items(
        db, select(Community).where(Community.status == "ACTIVE", Community.is_qa.is_(False), Community.name.contains(q)), Community, cursor, limit
    )
    return {"items": [community_payload(item) for item in items], "next_cursor": next_cursor}


@router.get("/api/v1/admin/communities")
def list_admin_communities(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    items, next_cursor = paginated_items(db, select(Community), Community, cursor, limit)
    community_ids = [item.id for item in items]
    counts = {}
    previews = {}
    if community_ids:
        counts = dict(db.execute(
            select(Cat.community_id, func.count(Cat.id)).where(Cat.community_id.in_(community_ids)).group_by(Cat.community_id)
        ).all())
        ranked = select(
            Cat.id.label("id"), Cat.community_id.label("community_id"), Cat.nickname.label("nickname"),
            Cat.code.label("code"),
            func.row_number().over(
                partition_by=Cat.community_id,
                order_by=(Cat.created_at.desc(), Cat.id.desc()),
            ).label("preview_rank"),
        ).where(Cat.community_id.in_(community_ids)).subquery()
        rows = db.execute(select(ranked).where(ranked.c.preview_rank <= 3)).mappings().all()
        for row in rows:
            previews.setdefault(row["community_id"], []).append({
                "id": row["id"], "nickname": row["nickname"], "code": row["code"],
            })
    merged_ids = {item.merged_into_id for item in items if item.merged_into_id}
    merged_names = dict(db.execute(select(Community.id, Community.name).where(Community.id.in_(merged_ids))).all()) if merged_ids else {}
    return {"items": [
        admin_community_payload(
            item, counts.get(item.id, 0), previews.get(item.id, []), merged_names.get(item.merged_into_id, "")
        ) for item in items
    ], "next_cursor": next_cursor}


@router.post("/api/v1/communities", status_code=201)
def create_community(payload: CommunityCreate, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    actor_id, role = actor
    try:
        normalized_name = normalize_community_name(payload.name)
    except ValueError:
        error(422, "invalid_community_name")
    duplicate = db.scalar(select(Community).where(
        Community.city == "杭州市", Community.district == "富阳区",
        Community.normalized_name == normalized_name,
        Community.status.notin_(["MERGED", "REJECTED", "ARCHIVED", "HIDDEN"]),
    ))
    if duplicate:
        error(409, "community_exists")
    item = Community(name=payload.name.strip(), normalized_name=normalized_name, street=payload.street.strip(), status="ACTIVE" if role in {"ADMIN", "SUPER_ADMIN"} else "PENDING_REVIEW", created_by=actor_id, is_qa=is_qa_label(payload.name))
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        error(409, "community_exists")
    audit(db, actor_id, "CREATE", "community", item.id, after=community_payload(item))
    db.commit()
    return community_payload(item)


@router.patch("/api/v1/communities/{community_id}")
def edit_community(community_id: str, payload: CommunityEdit, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    item = db.scalar(select(Community).where(Community.id == community_id).with_for_update())
    if not item:
        error(404, "community_not_found")
    is_admin = actor[1] in {"ADMIN", "SUPER_ADMIN"}
    if not is_admin and item.created_by != actor[0]:
        error(403, "community_edit_forbidden")
    if not is_admin and item.status not in {"PENDING_REVIEW", "NEEDS_CHANGES"}:
        error(409, "community_not_editable")
    if is_admin and item.status in {"MERGED", "REJECTED", "ARCHIVED"}:
        error(409, "community_not_editable")
    if payload.version != item.version:
        error(409, "stale_community_version")
    before = community_payload(item)
    try:
        normalized_name = normalize_community_name(payload.name)
    except ValueError:
        error(422, "invalid_community_name")
    duplicate = db.scalar(select(Community).where(
        Community.id != item.id,
        Community.city == item.city,
        Community.district == item.district,
        Community.normalized_name == normalized_name,
        Community.status.notin_(["MERGED", "REJECTED", "ARCHIVED", "HIDDEN"]),
    ))
    if duplicate:
        error(409, "community_exists")
    item.normalized_name = normalized_name
    item.name = payload.name.strip()
    item.street = payload.street.strip()
    item.review_note = payload.note.strip()
    if not is_admin:
        item.status = "PENDING_REVIEW"
    item.version += 1
    audit(db, actor[0], "UPDATE", "community", item.id, before, community_payload(item))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        error(409, "community_exists")
    except StaleDataError:
        db.rollback()
        error(409, "stale_community_version")
    return community_payload(item)


@router.post("/api/v1/communities/{community_id}/archive")
def archive_community(community_id: str, payload: CommunityArchive, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    item = db.scalar(select(Community).where(Community.id == community_id).with_for_update())
    if not item:
        error(404, "community_not_found")
    if payload.version != item.version:
        error(409, "stale_community_version")
    before = {"status": item.status}
    item.status = "ARCHIVED"
    item.version += 1
    audit(db, actor[0], "ARCHIVE", "community", item.id, before, {"status": item.status})
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_community_version")
    return community_payload(item)


@router.post("/api/v1/communities/{community_id}/review")
def review_community(community_id: str, payload: CommunityReview, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    item = db.scalar(select(Community).where(Community.id == community_id).with_for_update())
    if not item:
        error(404, "community_not_found")
    if item.status not in {"PENDING_REVIEW", "NEEDS_CHANGES"}:
        error(409, "community_review_state_invalid")
    if payload.version is not None and payload.version != item.version:
        error(409, "stale_community_version")
    if payload.approved is not None and item.version != 1:
        error(409, "legacy_review_version_required")
    if payload.action in {"request_changes", "reject"} and not payload.note.strip():
        error(422, "review_note_required")
    target = ("ACTIVE" if payload.approved else "HIDDEN") if payload.approved is not None else {
        "approve": "ACTIVE", "request_changes": "NEEDS_CHANGES", "reject": "REJECTED",
    }[payload.action]
    if target == "ACTIVE":
        # 版本已在上面校验过，这里只做"开放"这件事 —— 与后台批量共用同一段实现。
        approve_community(db, item, actor[0], note=payload.note)
        return community_payload(item)
    before = community_payload(item)
    item.status = target
    item.review_note = payload.note.strip()
    item.reviewed_by = actor[0]
    item.version += 1
    audit(db, actor[0], "REVIEW", "community", item.id, before, community_payload(item))
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_community_version")
    return community_payload(item)


@router.post("/api/v1/communities/{community_id}/merge")
def merge_community(community_id: str, payload: CommunityMerge, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    source = db.scalar(select(Community).where(Community.id == community_id).with_for_update())
    if not source:
        error(404, "community_not_found")
    if source.status not in {"PENDING_REVIEW", "NEEDS_CHANGES"}:
        error(409, "community_merge_state_invalid")
    if payload.version != source.version:
        error(409, "stale_community_version")
    if payload.target_community_id == source.id:
        error(409, "community_merge_target_invalid")
    target = db.scalar(select(Community).where(Community.id == payload.target_community_id).with_for_update())
    if not target or target.status != "ACTIVE":
        error(409, "community_merge_target_invalid")
    linked_cats = db.scalars(select(Cat).where(Cat.community_id == source.id).with_for_update()).all()
    for cat in linked_cats:
        before_cat = {"community_id": cat.community_id, "version": cat.version}
        cat.community_id = target.id
        cat.version += 1
        audit(db, actor[0], "COMMUNITY_REASSIGN", "cat", cat.id, before_cat, {"community_id": target.id, "version": cat.version})
    before = community_payload(source)
    source.status = "MERGED"
    source.merged_into_id = target.id
    source.reviewed_by = actor[0]
    source.version += 1
    audit(db, actor[0], "MERGE", "community", source.id, before, community_payload(source))
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_community_version")
    return community_payload(source)
