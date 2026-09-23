"""猫咪档案：建档、导入、审核、发布与时间线。"""

from .. import auto_review
from ..auth import require_admin
from ..community_rules import normalize_community_name
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..media import PUBLIC_IMAGE_FORMATS, sanitize_public_image
from ..models import Session as AuthSession, Cat, CatEvent, Community, DailyCatQuota, MediaAsset, User, new_id
from ..pagination import paginated_items
from ..reviews import approve_cat, reject_cat
from ..schemas import CatAdminEdit, CatCommunityReassign, CatCreate, CatEventCreate, ReviewRequest, VisibilityRequest
from ..serializers import audit, cat_event_payload, cat_payload, community_payload, is_qa_label, media_payload, normalized_idempotency_key, normalized_profile_key
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi import Depends, File, Form, Header, Query, Request, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.exc import StaleDataError
from typing import Optional
from dataclasses import dataclass
from zoneinfo import ZoneInfo
import secrets


router = APIRouter()


@router.get("/api/v1/cats")
def list_cats(q: str = "", community_id: Optional[str] = None, cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), authorization: Optional[str] = Header(default=None), db: DbSession = Depends(get_db)):
    is_admin = False
    if authorization and authorization.startswith("Bearer "):
        session = db.scalar(select(AuthSession).where(AuthSession.token == authorization[7:].strip()))
        if session:
            user = db.get(User, session.user_id)
            expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
            is_admin = bool(
                user and user.role in {"ADMIN", "SUPER_ADMIN"} and user.status == "ACTIVE"
                and session.revoked_at is None and expires_at >= datetime.now(timezone.utc)
            )
    stmt = select(Cat).join(Community, Cat.community_id == Community.id)
    if not is_admin:
        stmt = stmt.where(Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE", Cat.is_qa.is_(False), Community.status == "ACTIVE", Community.is_qa.is_(False))
    if community_id:
        stmt = stmt.where(Cat.community_id == community_id)
    if q:
        stmt = stmt.where(or_(Cat.nickname.contains(q), Cat.code.contains(q), Community.name.contains(q)))
    items, next_cursor = paginated_items(db, stmt, Cat, cursor, limit)
    return {"items": [cat_payload(item) for item in items], "next_cursor": next_cursor}


@dataclass
class SubmissionDecision:
    """一次投稿的审核判定：状态 + 要不要连小区一起开 + 该写什么审计。"""

    review_status: str
    activate_community: bool
    mode: str
    cat_audit: dict
    community_audit: Optional[dict] = None
    auto_approved: bool = False

    def record_audit(self, db, actor_id: str, cat_id: str, community) -> None:
        """把判定写进审计。shadow 模式也写 —— 那份数据就是用来决定要不要开启的。"""
        if self.mode == auto_review.MODE_OFF:
            return
        action = "AUTO_APPROVE" if self.auto_approved else "AUTO_REVIEW"
        if self.community_audit is not None:
            audit(db, actor_id, action, "community", community.id, before={"status": "PENDING_REVIEW"},
                  after=dict(self.community_audit, mode=self.mode, auto_approved=self.auto_approved))
        audit(db, actor_id, action, "cat", cat_id, after=dict(self.cat_audit, mode=self.mode, auto_approved=self.auto_approved))


def _submission_decision(db, request, role, *, new_community, community, nickname, location_note,
                         health_status, has_photo) -> SubmissionDecision:
    """普通用户的投稿要不要直接公开。

    管理员照旧免审。其余按 `HELPCAT_AUTO_REVIEW`：

    * `off`    —— 一律进待审（默认）；
    * `shadow` —— 只算、只写审计，状态不变；
    * `on`     —— 规则全过就公开，并且**连待审小区一起开放**（小区不开放，猫通过了也看不见）。

    规则本身在 `helpcat.auto_review`，这里只负责把结论落到状态与审计上。
    """
    if role in {"ADMIN", "SUPER_ADMIN"}:
        return SubmissionDecision("APPROVED", True, auto_review.MODE_OFF, {})

    mode = getattr(request.app.state.settings, "auto_review", auto_review.MODE_OFF)
    if mode not in auto_review.MODES:
        mode = auto_review.MODE_OFF

    community_decision = None
    if new_community:
        known_streets = set(db.scalars(select(Community.street).where(Community.status == "ACTIVE")).all())
        community_decision = auto_review.community_decision(
            name=community.name, street=community.street, known_streets=known_streets)

    will_open_community = community.status == "ACTIVE" or bool(community_decision and community_decision.approved)
    cat_decision = auto_review.cat_decision(
        nickname=nickname, location_note=location_note, health_status=health_status,
        has_photo=has_photo, community_is_active=will_open_community,
    )
    would_approve = cat_decision.approved and (community_decision is None or community_decision.approved)

    decision = SubmissionDecision(
        review_status="PENDING_REVIEW",
        activate_community=False,
        mode=mode,
        cat_audit=dict(cat_decision.as_audit(), would_approve=would_approve),
        community_audit=dict(community_decision.as_audit()) if community_decision else None,
    )
    if mode == auto_review.MODE_ON and would_approve:
        return SubmissionDecision("APPROVED", bool(community_decision and community_decision.approved), mode,
                                  decision.cat_audit, decision.community_audit, auto_approved=True)
    return decision


@router.post("/api/v1/cats", status_code=201)
def create_cat(request: Request, payload: CatCreate, actor=Depends(get_current_user), idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"), db: DbSession = Depends(get_db)):
    actor_id, role = actor
    if idempotency_key:
        idempotency_key = normalized_idempotency_key(idempotency_key)
        existing = db.scalar(select(Cat).where(Cat.created_by == actor_id, Cat.idempotency_key == idempotency_key))
        if existing:
            return cat_payload(existing)
    photo_asset = None
    if payload.photo_asset_id:
        photo_asset = db.get(MediaAsset, payload.photo_asset_id)
        if not photo_asset or photo_asset.created_by != actor_id:
            error(403, "photo_asset_forbidden")
    if role not in {"ADMIN", "SUPER_ADMIN"}:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        quota = db.scalar(select(DailyCatQuota).where(DailyCatQuota.user_id == actor_id, DailyCatQuota.quota_date == today).with_for_update())
        if not quota:
            quota = DailyCatQuota(user_id=actor_id, quota_date=today, used_count=0)
            db.add(quota)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                quota = db.scalar(select(DailyCatQuota).where(DailyCatQuota.user_id == actor_id, DailyCatQuota.quota_date == today).with_for_update())
        if quota.used_count >= 3:
            db.rollback()
            error(429, "daily_cat_limit_reached")
        quota.used_count += 1

    new_community = False
    if payload.community_id:
        community = db.get(Community, payload.community_id)
        if not community or community.status != "ACTIVE":
            error(404, "community_not_found")
    else:
        candidate = payload.community_candidate
        try:
            normalized_name = normalize_community_name(candidate.name)
        except ValueError:
            error(422, "invalid_community_name")
        community = db.scalar(
            select(Community).where(
                Community.city == "杭州市",
                Community.district == "富阳区",
                Community.normalized_name == normalized_name,
                Community.status.in_(["ACTIVE", "PENDING_REVIEW", "NEEDS_CHANGES"]),
            ).order_by((Community.status == "ACTIVE").desc(), Community.updated_at.desc())
        )
        if not community:
            new_community = True
            community = Community(
                name=candidate.name.strip(),
                normalized_name=normalized_name,
                street=candidate.street.strip(),
                review_note=candidate.note.strip(),
                status="ACTIVE" if role in {"ADMIN", "SUPER_ADMIN"} else "PENDING_REVIEW",
                created_by=actor_id,
                is_qa=is_qa_label(candidate.name),
            )
            db.add(community)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                error(409, "community_exists")
            audit(db, actor_id, "CREATE", "community", community.id, after=community_payload(community))
    submission = _submission_decision(
        db, request, role,
        new_community=new_community, community=community,
        nickname=payload.nickname, location_note=payload.location_note,
        health_status=payload.health_status, has_photo=bool(photo_asset),
    )
    review_status = submission.review_status
    if submission.activate_community:
        community.status = "ACTIVE"
    cat = Cat(community_id=community.id, code="HC-" + secrets.token_hex(4).upper(), nickname=payload.nickname.strip(),
              living_status=payload.living_status.strip(), health_status=payload.health_status.strip(), location_note=payload.location_note.strip(),
              latitude=payload.latitude, longitude=payload.longitude,
              review_status=review_status, created_by=actor_id,
              idempotency_key=idempotency_key,
              is_qa=is_qa_label(payload.nickname) or community.is_qa,
              photo_asset_id=photo_asset.id if photo_asset else None)
    db.add(cat)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(select(Cat).where(Cat.created_by == actor_id, Cat.idempotency_key == idempotency_key))
            if existing:
                return cat_payload(existing)
        error(409, "cat_create_conflict")
    audit(db, actor_id, "CREATE", "cat", cat.id, after=cat_payload(cat))
    submission.record_audit(db, actor_id, cat.id, community)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_cat_version")
    return cat_payload(cat)


@router.post("/api/v1/admin/cat-drafts/import", status_code=201)
async def import_cat_draft(request: Request, 
    file: UploadFile = File(...),
    community_id: str = Form(...),
    profile_key: str = Form(...),
    nickname: str = Form(...),
    living_status: str = Form(default=""),
    health_status: str = Form(default="UNKNOWN"),
    location_note: str = Form(...),
    actor=Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: DbSession = Depends(get_db),
):
    require_admin(actor)
    key = normalized_profile_key(profile_key)
    request_key = normalized_idempotency_key(idempotency_key)
    clean_nickname = nickname.strip()
    clean_living_status = living_status.strip()
    clean_health_status = health_status.strip()
    clean_location_note = location_note.strip()
    if not 1 <= len(clean_nickname) <= 80 or len(clean_living_status) > 80 or not 1 <= len(clean_health_status) <= 80 or not 1 <= len(clean_location_note) <= 240:
        error(422, "invalid_draft_fields")
    existing_request = db.scalar(
        select(Cat).where(Cat.created_by == actor[0], Cat.idempotency_key == request_key)
    )
    if existing_request:
        if existing_request.profile_key != key:
            error(409, "idempotency_key_reused")
        asset = db.get(MediaAsset, existing_request.photo_asset_id)
        if not asset:
            error(409, "draft_media_missing")
        return {"changed": False, "cat": cat_payload(existing_request), "media": media_payload(asset)}
    existing_profile = db.scalar(select(Cat).where(Cat.profile_key == key))
    if existing_profile:
        if existing_profile.idempotency_key and existing_profile.idempotency_key != request_key:
            error(409, "profile_key_exists")
        asset = db.get(MediaAsset, existing_profile.photo_asset_id)
        if not asset:
            error(409, "draft_media_missing")
        if not existing_profile.idempotency_key:
            existing_profile.idempotency_key = request_key
            db.commit()
        return {"changed": False, "cat": cat_payload(existing_profile), "media": media_payload(asset)}
    community = db.get(Community, community_id)
    if not community or community.status != "ACTIVE":
        error(404, "community_not_found")
    allowed_content_types = {item[0] for item in PUBLIC_IMAGE_FORMATS.values()}
    if file.content_type not in allowed_content_types:
        error(415, "unsupported_image_type")
    content = await file.read(request.app.state.settings.max_image_bytes + 1)
    if len(content) > request.app.state.settings.max_image_bytes:
        error(413, "image_too_large")
    sanitized, content_type, extension = sanitize_public_image(
        content, file.content_type, request.app.state.settings.max_image_pixels, request.app.state.settings.max_image_bytes,
    )
    object_key = new_id() + extension
    asset = MediaAsset(
        id=new_id(), object_key=object_key, content_type=content_type,
        byte_size=len(sanitized), created_by=actor[0],
    )
    cat = Cat(
        id=new_id(), community_id=community.id, community=community,
        code="HC-" + secrets.token_hex(4).upper(), nickname=clean_nickname,
        living_status=clean_living_status, health_status=clean_health_status,
        location_note=clean_location_note, photo_asset_id=asset.id,
        review_status="PENDING_REVIEW", visibility_status="HIDDEN",
        created_by=actor[0], idempotency_key=request_key, profile_key=key,
        is_qa=is_qa_label(clean_nickname) or community.is_qa,
    )
    target = request.app.state.settings.storage_root / object_key
    staging = request.app.state.settings.storage_root / ("." + object_key + "." + new_id() + ".tmp")
    try:
        staging.write_bytes(sanitized)
        db.add_all([asset, cat])
        db.flush()
        audit(db, actor[0], "UPLOAD", "media", asset.id, after=media_payload(asset))
        audit(db, actor[0], "CREATE", "cat", cat.id, after=cat_payload(cat))
        staging.replace(target)
        db.commit()
    except IntegrityError:
        db.rollback()
        staging.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        concurrent = db.scalar(
            select(Cat).where(Cat.created_by == actor[0], Cat.idempotency_key == request_key)
        )
        if concurrent and concurrent.profile_key == key:
            concurrent_asset = db.get(MediaAsset, concurrent.photo_asset_id)
            if concurrent_asset:
                return {"changed": False, "cat": cat_payload(concurrent), "media": media_payload(concurrent_asset)}
            error(409, "draft_media_missing")
        error(409, "profile_key_exists")
    except Exception:
        db.rollback()
        staging.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return {"changed": True, "cat": cat_payload(cat), "media": media_payload(asset)}

def get_cat_or_404(db, cat_id):
    cat = db.get(Cat, cat_id)
    if not cat:
        error(404, "cat_not_found")
    return cat


@router.patch("/api/v1/admin/cats/{cat_id}")
def edit_cat(cat_id: str, payload: CatAdminEdit, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    cat = db.scalar(select(Cat).where(Cat.id == cat_id).with_for_update())
    if not cat:
        error(404, "cat_not_found")
    if payload.version is not None and payload.version != cat.version:
        error(409, "version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("version", None)
    if changes.get("photo_asset_id") is not None and not db.get(MediaAsset, changes["photo_asset_id"]):
        error(404, "media_not_found")
    before = {field: getattr(cat, field) for field in changes}
    before["version"] = cat.version
    for field, value in changes.items():
        setattr(cat, field, value)
    cat.version += 1
    after = {field: getattr(cat, field) for field in changes}
    after["version"] = cat.version
    audit(db, actor[0], "UPDATE", "cat", cat.id, before, after)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "version_conflict")
    return cat_payload(cat)


@router.post("/api/v1/cats/{cat_id}/community")
def reassign_cat_community(cat_id: str, payload: CatCommunityReassign, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    cat = db.scalar(select(Cat).where(Cat.id == cat_id).with_for_update())
    if not cat:
        error(404, "cat_not_found")
    if payload.version != cat.version:
        error(409, "stale_cat_version")
    target = db.get(Community, payload.community_id)
    if not target or target.status != "ACTIVE":
        error(409, "community_reassign_target_invalid")
    before = {"community_id": cat.community_id, "version": cat.version}
    cat.community_id = target.id
    cat.version += 1
    audit(db, actor[0], "COMMUNITY_REASSIGN", "cat", cat.id, before, {"community_id": target.id, "version": cat.version})
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_cat_version")
    return cat_payload(cat)


@router.post("/api/v1/cats/{cat_id}/review")
def review_cat(cat_id: str, payload: ReviewRequest, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    cat = get_cat_or_404(db, cat_id)
    # 单条与后台批量走同一段实现，避免两边校验分叉。
    if payload.approved:
        approve_cat(db, cat, actor[0])
    else:
        reject_cat(db, cat, actor[0])
    return cat_payload(cat)


@router.post("/api/v1/cats/{cat_id}/visibility")
def set_visibility(cat_id: str, payload: VisibilityRequest, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    cat = get_cat_or_404(db, cat_id)
    before = {"visibility_status": cat.visibility_status}
    cat.visibility_status = "ACTIVE" if payload.visible else "HIDDEN"
    cat.version += 1
    audit(db, actor[0], "VISIBILITY", "cat", cat.id, before, {"visibility_status": cat.visibility_status})
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_cat_version")
    return cat_payload(cat)


@router.post("/api/v1/cats/{cat_id}/archive")
def archive_cat(cat_id: str, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    cat = get_cat_or_404(db, cat_id)
    before = {"visibility_status": cat.visibility_status}
    cat.visibility_status = "ARCHIVED"
    cat.version += 1
    audit(db, actor[0], "ARCHIVE", "cat", cat.id, before, {"visibility_status": cat.visibility_status})
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "stale_cat_version")
    return cat_payload(cat)


@router.get("/api/v1/me/submissions")
def my_submissions(cat_cursor: Optional[str] = None, community_cursor: Optional[str] = None,
                   cat_done: bool = False, community_done: bool = False,
                   limit: int = Query(default=24, ge=1, le=100), actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    cats, next_cat_cursor = ([], None) if cat_done else paginated_items(
        db, select(Cat).where(Cat.created_by == actor[0]), Cat, cat_cursor, limit
    )
    communities, next_community_cursor = ([], None) if community_done else paginated_items(
        db, select(Community).where(Community.created_by == actor[0]), Community, community_cursor, limit
    )
    merged_ids = {item.merged_into_id for item in communities if item.merged_into_id}
    merged_names = dict(db.execute(select(Community.id, Community.name).where(Community.id.in_(merged_ids))).all()) if merged_ids else {}
    community_results = []
    for item in communities:
        value = community_payload(item)
        value["merged_into_name"] = merged_names.get(item.merged_into_id, "")
        community_results.append(value)
    return {
        "cats": [cat_payload(item) for item in cats],
        "communities": community_results,
        "next_cursor": {"cats": next_cat_cursor, "communities": next_community_cursor},
    }


@router.get("/api/v1/cats/{cat_id}/events")
def list_cat_events(cat_id: str, db: DbSession = Depends(get_db)):
    cat = db.scalar(
        select(Cat).join(Community, Cat.community_id == Community.id).where(
            Cat.id == cat_id, Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE",
            Cat.is_qa.is_(False), Community.status == "ACTIVE", Community.is_qa.is_(False),
        )
    )
    if not cat:
        error(404, "cat_not_found")
    rows = db.scalars(select(CatEvent).where(
        CatEvent.cat_id == cat.id, CatEvent.is_qa.is_(False),
    ).order_by(CatEvent.occurred_at.asc())).all()
    return {"items": [cat_event_payload(item) for item in rows]}


@router.post("/api/v1/admin/cats/{cat_id}/events", status_code=201)
def create_cat_event(
    cat_id: str,
    payload: CatEventCreate,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    require_admin(actor)
    cat = db.get(Cat, cat_id)
    if not cat:
        error(404, "cat_not_found")
    item = CatEvent(
        cat_id=cat.id, kind=payload.kind, title=payload.title.strip(), detail=payload.detail,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc), created_by=actor[0], is_qa=False,
    )
    db.add(item)
    db.flush()
    audit(db, actor[0], "CREATE", "cat_event", item.id, after={"cat_id": cat.id, "kind": item.kind})
    db.commit()
    return cat_event_payload(item)
