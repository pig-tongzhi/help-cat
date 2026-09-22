import json
import math
import mimetypes
import secrets
import base64
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.exc import StaleDataError
from PIL import Image, ImageOps, UnidentifiedImageError

from .auth import DUMMY_PASSWORD_HASH, WechatProvider, current_user_factory, hash_password, issue_session, require_admin, require_super_admin, verify_password
from .config import Settings
from .community_rules import normalize_community_name
from .db import Base, ensure_schema, make_session_factory
from .models import AuditLog, Cat, CatEvent, Community, DailyCatQuota, FeedingLog, FeedingPoint, ImpactEvent, LeadMessage, MediaAsset, Session as AuthSession, Task, User, new_id
from .schemas import CatCommunityReassign, CatCreate, CatEventCreate, CommunityArchive, CommunityCreate, CommunityEdit, CommunityMerge, CommunityReview, FeedingLogCreate, FeedingPointCreate, FeedingPointEdit, ImpactEventCreate, LeadMessageCreate, LeadMessageStatusUpdate, PasswordLoginRequest, RegisterRequest, ReviewRequest, RoleUpdate, TaskCancel, TaskComplete, TaskCreate, TaskReassign, VisibilityRequest, WechatLoginRequest


def error(status, code, message=None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message or code})


PUBLIC_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
MEDIA_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
MEDIA_THUMBNAIL_SIZE = 640


def media_thumbnail_path(storage_root, object_key):
    return storage_root / (Path(object_key).stem + ".thumb.webp")


def create_media_thumbnail(source_path, target_path):
    """Create a small, metadata-free list thumbnail without changing the original asset."""
    with Image.open(source_path) as source:
        thumbnail = ImageOps.exif_transpose(source).convert("RGB")
        thumbnail.thumbnail((MEDIA_THUMBNAIL_SIZE, MEDIA_THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        thumbnail.save(output, format="WEBP", quality=76, method=6)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary_path.write_bytes(output.getvalue())
    temporary_path.replace(target_path)


def sanitize_public_image(content, claimed_content_type, max_image_pixels, max_image_bytes):
    """Fully decode and safely re-encode one public image without source metadata."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            image_format = source.format
            expected = PUBLIC_IMAGE_FORMATS.get(image_format)
            if not expected or expected[0] != claimed_content_type:
                error(415, "image_content_mismatch")
            frame_count = int(getattr(source, "n_frames", 1) or 1)
            decoded_pixels = source.width * source.height * frame_count
            if decoded_pixels > max_image_pixels:
                error(413, "image_too_many_pixels")
            for frame_index in range(frame_count):
                source.seek(frame_index)
                source.load()
            source.seek(0)
            sanitized = ImageOps.exif_transpose(source)
            if image_format == "JPEG":
                if sanitized.mode not in {"RGB", "L"}:
                    sanitized = sanitized.convert("RGB")
            elif sanitized.mode not in {"RGB", "RGBA", "L", "LA"}:
                sanitized = sanitized.convert("RGBA" if "transparency" in source.info else "RGB")
            output = io.BytesIO()
            if image_format == "JPEG":
                sanitized.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
            elif image_format == "PNG":
                sanitized.save(output, format="PNG", optimize=True, compress_level=9)
            else:
                sanitized.save(output, format="WEBP", quality=85, method=6)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError):
        error(415, "image_content_mismatch")
    sanitized_content = output.getvalue()
    if len(sanitized_content) > max_image_bytes:
        error(413, "image_too_large")
    return sanitized_content, expected[0], expected[1]


def cat_payload(cat):
    community_status = cat.community.status if cat.community else None
    return {"id": cat.id, "community_id": cat.community_id, "code": cat.code, "nickname": cat.nickname,
            "living_status": cat.living_status, "health_status": cat.health_status, "location_note": cat.location_note,
            "review_status": cat.review_status, "visibility_status": cat.visibility_status, "created_by": cat.created_by,
            "photo_asset_id": cat.photo_asset_id, "profile_key": cat.profile_key,
            "latitude": cat.latitude, "longitude": cat.longitude,
            "community_name": cat.community.name if cat.community else "",
            "community_street": cat.community.street if cat.community else "",
            "version": cat.version,
            "community_status": community_status,
            "community_review_blocker": None if community_status == "ACTIVE" else "COMMUNITY_" + community_status}


def community_payload(item):
    return {"id": item.id, "city": item.city, "district": item.district, "street": item.street, "name": item.name,
            "status": item.status, "created_by": item.created_by, "review_note": item.review_note,
            "merged_into_id": item.merged_into_id, "version": item.version}


def admin_community_payload(item, linked_count=0, linked_cats=None, merged_into_name=""):
    result = community_payload(item)
    result.update({
        "linked_cat_count": linked_count,
        "linked_cats": linked_cats or [],
        "merged_into_name": merged_into_name,
    })
    return result


def task_payload(item):
    return {"id": item.id, "title": item.title, "description": item.description, "community_id": item.community_id,
            "status": item.status, "created_by": item.created_by, "claimed_by": item.claimed_by}


def iso_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def impact_event_payload(item):
    return {
        "id": item.id, "kind": item.kind, "amount": item.amount, "note": item.note,
        "occurred_at": iso_utc(item.occurred_at), "created_by": item.created_by,
        "reversed_at": iso_utc(item.reversed_at),
        "reversed_by": item.reversed_by, "is_qa": item.is_qa,
    }


def media_payload(asset):
    return {"id": asset.id, "object_key": asset.object_key, "content_type": asset.content_type, "byte_size": asset.byte_size}


def user_payload(user):
    return {"id": user.id, "username": user.username, "nickname": user.nickname, "role": user.role,
            "status": user.status, "created_at": user.created_at.isoformat()}


def audit(db, actor_id, action, entity_type, entity_id, before=None, after=None):
    db.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                    before_json=json.dumps(before or {}, ensure_ascii=False), after_json=json.dumps(after or {}, ensure_ascii=False)))


def is_qa_label(value):
    return str(value or "").lstrip().startswith("[QA-")


def normalized_idempotency_key(value):
    key = str(value or "").strip()
    if not 8 <= len(key) <= 64 or not all(character.isalnum() or character in "-_.:" for character in key):
        error(422, "invalid_idempotency_key")
    return key


def normalized_profile_key(value):
    key = str(value or "").strip()
    if not 3 <= len(key) <= 64 or not all(character.islower() or character.isdigit() or character == "-" for character in key):
        error(422, "invalid_profile_key")
    if key.startswith("-") or key.endswith("-") or "--" in key:
        error(422, "invalid_profile_key")
    return key


def encode_cursor(item):
    raw = item.created_at.isoformat() + "|" + item.id
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value):
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        created_at, entity_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(created_at), entity_id
    except (ValueError, UnicodeDecodeError):
        error(422, "invalid_cursor")


def paginated_items(db, stmt, model, cursor, limit):
    if cursor:
        created_at, entity_id = decode_cursor(cursor)
        stmt = stmt.where(or_(model.created_at < created_at, and_(model.created_at == created_at, model.id < entity_id)))
    rows = db.scalars(stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return rows, encode_cursor(rows[-1]) if has_more and rows else None


def lead_message_payload(item):
    return {
        "id": item.id,
        "name": item.name,
        "contact_type": item.contact_type,
        "contact": item.contact,
        "message": item.message,
        "source": item.source,
        "status": item.status,
        "admin_note": item.admin_note,
        "created_at": iso_utc(item.created_at),
        "handled_at": iso_utc(item.handled_at),
    }


def task_payload(item, community_name="", claimed_by_username="", evidence_available=False):
    return {
        "id": item.id, "title": item.title, "description": item.description, "community_id": item.community_id,
        "community_name": community_name, "status": item.status, "created_by": item.created_by,
        "claimed_by": item.claimed_by, "claimed_by_username": claimed_by_username,
        "claimed_at": iso_utc(item.claimed_at), "completed_at": iso_utc(item.completed_at),
        "completion_note": item.completion_note, "evidence_asset_id": item.evidence_asset_id,
        "evidence_available": bool(evidence_available or item.evidence_asset_id),
        "cancelled_at": iso_utc(item.cancelled_at), "cancel_reason": item.cancel_reason,
        "created_at": iso_utc(item.created_at),
    }


def feeding_point_payload(item, fed_today=0, fed_by_me=False, last_fed_at=None, community_name="", distance_m=None, needs_feed=None):
    return {
        "id": item.id, "name": item.name, "community_id": item.community_id, "community_name": community_name,
        "location_note": item.location_note, "feeding_time": item.feeding_time,
        "caretaker_note": item.caretaker_note, "status": item.status,
        "latitude": item.latitude, "longitude": item.longitude,
        "fed_today": fed_today, "fed_by_me": fed_by_me, "last_fed_at": iso_utc(last_fed_at),
        "distance_m": distance_m, "needs_feed": not fed_today if needs_feed is None else needs_feed,
    }


def feeding_log_payload(item, point_name=""):
    return {
        "id": item.id, "point_id": item.point_id, "point_name": point_name, "user_id": item.user_id,
        "fed_on": item.fed_on, "fed_at": iso_utc(item.fed_at), "food_note": item.food_note,
        "note": item.note, "photo_asset_id": item.photo_asset_id,
    }


def cat_event_payload(item):
    return {
        "id": item.id, "cat_id": item.cat_id, "kind": item.kind, "title": item.title,
        "detail": item.detail, "occurred_at": iso_utc(item.occurred_at),
    }


def shanghai_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


EARTH_RADIUS_M = 6371000
FEEDING_STREAK_MILESTONES = (3, 7, 14, 30, 60)


def haversine_distance_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def feeding_point_today_sort_key(point, fed_today, last_fed_at):
    """Points nobody fed today first, then never-fed points, then the oldest feed."""
    return (
        0 if fed_today == 0 else 1,
        0 if last_fed_at is None else 1,
        last_fed_at.isoformat() if last_fed_at is not None else "",
        point.name,
    )


def community_names(db, ids):
    """Resolve the community names shown next to tasks and feeding points."""
    wanted = {value for value in ids if value}
    if not wanted:
        return {}
    rows = db.execute(select(Community.id, Community.name).where(Community.id.in_(wanted))).all()
    return {row[0]: row[1] for row in rows}


def create_app(database_url=None, storage_root=None, fake_admin_openids=None):
    settings = Settings(database_url=database_url, storage_root=storage_root, fake_admin_openids=fake_admin_openids)
    if settings.database_url.startswith("sqlite:///") and settings.database_url not in {"sqlite:///", "sqlite:///:memory:"}:
        Path(settings.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    engine, session_factory = make_session_factory(settings.database_url)
    ensure_schema(engine)
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Help Cat API", version="1.0.0")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.wechat_provider = WechatProvider(settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins or ["http://localhost"], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    current_user = current_user_factory(session_factory, settings)

    def optional_user(authorization: Optional[str] = Header(default=None)):
        """Public endpoints that behave differently for a signed-in visitor."""
        if not authorization or not authorization.startswith("Bearer "):
            return None
        try:
            return current_user(authorization)
        except HTTPException:
            return None

    @app.exception_handler(HTTPException)
    async def api_http_error(_, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    def db_session():
        with session_factory() as db:
            yield db

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "service": "help-cat-api", "version": "1.0.0"}

    @app.get("/api/v1/public/metrics")
    def public_metrics(db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/admin/impact-events", status_code=201)
    def create_impact_event(payload: ImpactEventCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.get("/api/v1/admin/impact-events")
    def list_impact_events(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        items, next_cursor = paginated_items(db, select(ImpactEvent), ImpactEvent, cursor, limit)
        return {"items": [impact_event_payload(item) for item in items], "next_cursor": next_cursor}

    @app.post("/api/v1/admin/impact-events/{event_id}/reverse")
    def reverse_impact_event(event_id: str, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.get("/api/v1/public/profiles/{profile_key}")
    def public_profile(profile_key: str, db: DbSession = Depends(db_session)):
        key = normalized_profile_key(profile_key)
        cat = db.scalar(
            select(Cat).join(Community, Cat.community_id == Community.id).where(
                Cat.profile_key == key, Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE",
                Cat.is_qa.is_(False), Community.status == "ACTIVE", Community.is_qa.is_(False),
            )
        )
        if not cat:
            error(404, "public_profile_not_found")
        return cat_payload(cat)

    @app.get("/api/v1/public/contact")
    def public_contact():
        """How a visitor reaches the operator.

        Public by design: the welcome page only renders it after the visitor
        taps "查看管理员联系方式", which is a UI affordance rather than a secret.
        """
        return {
            "wechat": settings.admin_wechat,
            "wechat_note": settings.admin_wechat_note,
            "phone": settings.admin_phone,
            "qr_image": settings.admin_qr_image,
            "note": settings.admin_contact_note,
        }

    @app.post("/api/v1/public/messages", status_code=201)
    def create_lead_message(payload: LeadMessageCreate, request: Request, db: DbSession = Depends(db_session)):
        """Accept a contact left by a visitor with no account."""
        client_ip = request.client.host if request.client else ""
        now = datetime.now(timezone.utc)
        if client_ip:
            recent = db.scalar(select(func.count()).select_from(LeadMessage).where(
                LeadMessage.client_ip == client_ip,
                LeadMessage.created_at >= now - timedelta(hours=1),
            )) or 0
            if recent >= settings.lead_rate_limit_per_hour:
                error(429, "too_many_messages")
        duplicate = db.scalar(select(LeadMessage).where(
            LeadMessage.contact == payload.contact,
            LeadMessage.created_at >= now - timedelta(minutes=settings.lead_dedupe_minutes),
        ).order_by(LeadMessage.created_at.desc()))
        if duplicate:
            # The same contact again is the same lead, not a new one.
            return lead_message_payload(duplicate)
        item = LeadMessage(
            name=payload.name,
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

    @app.get("/api/v1/admin/messages")
    def list_lead_messages(
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = Query(default=24, ge=1, le=100),
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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

    @app.post("/api/v1/admin/messages/{message_id}/status")
    def update_lead_message_status(
        message_id: str,
        payload: LeadMessageStatusUpdate,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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

    @app.post("/api/v1/auth/wechat-login")
    def wechat_login(payload: WechatLoginRequest, db: DbSession = Depends(db_session)):
        openid = app.state.wechat_provider.exchange_code(payload.code)
        user = db.scalar(select(User).where(User.openid == openid))
        if not user:
            role = "ADMIN" if openid in settings.fake_admin_openids else "USER"
            user = User(openid=openid, role=role, nickname="")
            db.add(user)
            db.flush()
        user.last_login_at = datetime.now(timezone.utc)
        token = issue_session(db, user, settings.session_days)
        db.commit()
        return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "role": user.role}}

    def auth_payload(db, user):
        token = issue_session(db, user, settings.session_days)
        return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "username": user.username, "role": user.role}}

    @app.post("/api/v1/auth/register", status_code=201)
    def register(payload: RegisterRequest, db: DbSession = Depends(db_session)):
        username = payload.username.strip()
        if db.scalar(select(User).where(User.username == username)):
            error(409, "username_exists")
        user = User(openid="local:" + username, username=username, password_hash=hash_password(payload.password), role="USER", nickname=username)
        db.add(user)
        db.flush()
        result = auth_payload(db, user)
        db.commit()
        return result

    @app.post("/api/v1/auth/login")
    def password_login(payload: PasswordLoginRequest, db: DbSession = Depends(db_session)):
        user = db.scalar(select(User).where(User.username == payload.username.strip()))
        candidate_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
        if not verify_password(payload.password, candidate_hash):
            error(401, "invalid_credentials")
        if user.status != "ACTIVE":
            error(403, "user_disabled")
        user.last_login_at = datetime.now(timezone.utc)
        result = auth_payload(db, user)
        db.commit()
        return result

    @app.post("/api/v1/auth/logout")
    def logout(actor=Depends(current_user), authorization: Optional[str] = Header(default=None), db: DbSession = Depends(db_session)):
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
        session = db.get(AuthSession, token)
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    def auth_me(actor=Depends(current_user), db: DbSession = Depends(db_session)):
        user = db.get(User, actor[0])
        return {"id": user.id, "username": user.username, "role": user.role}

    @app.get("/api/v1/communities")
    def list_communities(q: str = "", cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), db: DbSession = Depends(db_session)):
        items, next_cursor = paginated_items(
            db, select(Community).where(Community.status == "ACTIVE", Community.name.contains(q)), Community, cursor, limit
        )
        return {"items": [community_payload(item) for item in items], "next_cursor": next_cursor}

    @app.get("/api/v1/admin/communities")
    def list_admin_communities(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.get("/api/v1/admin/users")
    def list_admin_users(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_super_admin(actor)
        items, next_cursor = paginated_items(db, select(User), User, cursor, limit)
        return {"items": [user_payload(item) for item in items], "next_cursor": next_cursor}

    @app.post("/api/v1/admin/users/{user_id}/role")
    def update_user_role(user_id: str, payload: RoleUpdate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/communities", status_code=201)
    def create_community(payload: CommunityCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.patch("/api/v1/communities/{community_id}")
    def edit_community(community_id: str, payload: CommunityEdit, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/communities/{community_id}/archive")
    def archive_community(community_id: str, payload: CommunityArchive, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/communities/{community_id}/review")
    def review_community(community_id: str, payload: CommunityReview, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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
        before = community_payload(item)
        if payload.approved is not None:
            item.status = "ACTIVE" if payload.approved else "HIDDEN"
        else:
            item.status = {"approve": "ACTIVE", "request_changes": "NEEDS_CHANGES", "reject": "REJECTED"}[payload.action]
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

    @app.post("/api/v1/communities/{community_id}/merge")
    def merge_community(community_id: str, payload: CommunityMerge, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.get("/api/v1/cats")
    def list_cats(q: str = "", community_id: Optional[str] = None, cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), authorization: Optional[str] = Header(default=None), db: DbSession = Depends(db_session)):
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
            stmt = stmt.where(Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE", Community.status == "ACTIVE")
        if community_id:
            stmt = stmt.where(Cat.community_id == community_id)
        if q:
            stmt = stmt.where(or_(Cat.nickname.contains(q), Cat.code.contains(q), Community.name.contains(q)))
        items, next_cursor = paginated_items(db, stmt, Cat, cursor, limit)
        return {"items": [cat_payload(item) for item in items], "next_cursor": next_cursor}

    @app.post("/api/v1/cats", status_code=201)
    def create_cat(payload: CatCreate, actor=Depends(current_user), idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"), db: DbSession = Depends(db_session)):
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
        review_status = "APPROVED" if role in {"ADMIN", "SUPER_ADMIN"} else "PENDING_REVIEW"
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
        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            error(409, "stale_cat_version")
        return cat_payload(cat)

    @app.post("/api/v1/admin/cat-drafts/import", status_code=201)
    async def import_cat_draft(
        file: UploadFile = File(...),
        community_id: str = Form(...),
        profile_key: str = Form(...),
        nickname: str = Form(...),
        living_status: str = Form(default=""),
        health_status: str = Form(default="UNKNOWN"),
        location_note: str = Form(...),
        actor=Depends(current_user),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        db: DbSession = Depends(db_session),
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
        content = await file.read(settings.max_image_bytes + 1)
        if len(content) > settings.max_image_bytes:
            error(413, "image_too_large")
        sanitized, content_type, extension = sanitize_public_image(
            content, file.content_type, settings.max_image_pixels, settings.max_image_bytes,
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
        target = settings.storage_root / object_key
        staging = settings.storage_root / ("." + object_key + "." + new_id() + ".tmp")
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

    @app.post("/api/v1/cats/{cat_id}/community")
    def reassign_cat_community(cat_id: str, payload: CatCommunityReassign, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/cats/{cat_id}/review")
    def review_cat(cat_id: str, payload: ReviewRequest, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        cat = get_cat_or_404(db, cat_id)
        if payload.approved and cat.community.status != "ACTIVE":
            error(409, "community_not_active")
        before = {"review_status": cat.review_status}
        cat.review_status = "APPROVED" if payload.approved else "REJECTED"
        cat.version += 1
        audit(db, actor[0], "REVIEW", "cat", cat.id, before, {"review_status": cat.review_status})
        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            error(409, "stale_cat_version")
        return cat_payload(cat)

    @app.post("/api/v1/cats/{cat_id}/visibility")
    def set_visibility(cat_id: str, payload: VisibilityRequest, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/cats/{cat_id}/archive")
    def archive_cat(cat_id: str, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.get("/api/v1/me/submissions")
    def my_submissions(cat_cursor: Optional[str] = None, community_cursor: Optional[str] = None,
                       cat_done: bool = False, community_done: bool = False,
                       limit: int = Query(default=24, ge=1, le=100), actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/tasks", status_code=201)
    def create_task(payload: TaskCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        if payload.community_id and not db.get(Community, payload.community_id):
            error(404, "community_not_found")
        task = Task(title=payload.title.strip(), description=payload.description.strip(), community_id=payload.community_id, created_by=actor[0], is_qa=is_qa_label(payload.title))
        db.add(task)
        db.flush()
        audit(db, actor[0], "CREATE", "task", task.id, after={"title": task.title, "status": task.status})
        db.commit()
        return task_payload(task)

    @app.get("/api/v1/tasks")
    def list_tasks(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), db: DbSession = Depends(db_session)):
        items, next_cursor = paginated_items(db, select(Task).where(Task.status == "OPEN"), Task, cursor, limit)
        return {"items": [task_payload(item) for item in items], "next_cursor": next_cursor}

    @app.post("/api/v1/tasks/{task_id}/claim")
    def claim_task(task_id: str, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            error(404, "task_not_found")
        if task.status != "OPEN":
            error(409, "task_already_claimed")
        task.status = "CLAIMED"
        task.claimed_by = actor[0]
        task.claimed_at = datetime.now(timezone.utc)
        audit(db, actor[0], "CLAIM", "task", task.id, before={"status": "OPEN"}, after={"status": task.status, "claimed_by": actor[0]})
        db.commit()
        return task_payload(task)

    def task_users(db, tasks):
        ids = {value for task in tasks for value in (task.created_by, task.claimed_by) if value}
        if not ids:
            return {}
        rows = db.execute(select(User.id, User.username, User.nickname).where(User.id.in_(ids))).all()
        return {row[0]: (row[1] or row[2] or "") for row in rows}

    @app.get("/api/v1/tasks/mine")
    def list_my_tasks(
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = Query(default=24, ge=1, le=100),
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
    ):
        """Tasks this volunteer claimed, so they can report completion."""
        stmt = select(Task).where(Task.is_qa.is_(False), Task.claimed_by == actor[0])
        if status:
            stmt = stmt.where(Task.status == status)
        items, next_cursor = paginated_items(db, stmt, Task, cursor, limit)
        names = community_names(db, [item.community_id for item in items])
        users = task_users(db, items)
        return {
            "items": [task_payload(item, names.get(item.community_id, ""), users.get(item.claimed_by, "")) for item in items],
            "next_cursor": next_cursor,
        }

    @app.post("/api/v1/tasks/{task_id}/complete")
    def complete_task(
        task_id: str,
        payload: TaskComplete,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
    ):
        """The volunteer who claimed the task reports it done, optionally with a photo."""
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            error(404, "task_not_found")
        if actor[1] not in {"ADMIN", "SUPER_ADMIN"} and task.claimed_by != actor[0]:
            error(403, "task_not_yours")
        if task.status != "CLAIMED":
            error(409, "task_not_claimed")
        if payload.evidence_asset_id:
            asset = db.get(MediaAsset, payload.evidence_asset_id)
            if not asset or (asset.created_by != actor[0] and actor[1] not in {"ADMIN", "SUPER_ADMIN"}):
                error(403, "evidence_asset_forbidden")
        task.status = "COMPLETED"
        task.completed_at = datetime.now(timezone.utc)
        task.completion_note = payload.note
        task.evidence_asset_id = payload.evidence_asset_id
        audit(db, actor[0], "COMPLETE", "task", task.id, before={"status": "CLAIMED"}, after={
            "status": task.status, "evidence_asset_id": task.evidence_asset_id,
        })
        db.commit()
        return task_payload(task, community_names(db, [task.community_id]).get(task.community_id, ""))

    @app.post("/api/v1/tasks/{task_id}/cancel")
    def cancel_task(
        task_id: str,
        payload: TaskCancel,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
    ):
        require_admin(actor)
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            error(404, "task_not_found")
        if task.status in {"COMPLETED", "CANCELLED"}:
            error(409, "task_already_closed")
        before = {"status": task.status, "claimed_by": task.claimed_by}
        task.status = "CANCELLED"
        task.cancelled_at = datetime.now(timezone.utc)
        task.cancel_reason = payload.reason
        audit(db, actor[0], "CANCEL", "task", task.id, before=before, after={"status": task.status, "reason": payload.reason})
        db.commit()
        return task_payload(task)

    @app.post("/api/v1/tasks/{task_id}/reassign")
    def reassign_task(
        task_id: str,
        payload: TaskReassign,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
    ):
        """Hand a task to another volunteer, or release it back to the open pool.

        Administrators may reassign to anyone; a volunteer may only release
        the task they claimed themselves.
        """
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            error(404, "task_not_found")
        if actor[1] not in {"ADMIN", "SUPER_ADMIN"}:
            if payload.target_user_id or task.claimed_by != actor[0]:
                error(403, "forbidden")
        if task.status in {"COMPLETED", "CANCELLED"}:
            error(409, "task_already_closed")
        before = {"status": task.status, "claimed_by": task.claimed_by}
        if payload.target_user_id:
            target = db.get(User, payload.target_user_id)
            if not target or target.status != "ACTIVE":
                error(404, "target_user_not_found")
            task.status = "CLAIMED"
            task.claimed_by = target.id
            task.claimed_at = datetime.now(timezone.utc)
        else:
            task.status = "OPEN"
            task.claimed_by = None
            task.claimed_at = None
        audit(db, actor[0], "REASSIGN", "task", task.id, before=before, after={
            "status": task.status, "claimed_by": task.claimed_by,
        })
        db.commit()
        users = task_users(db, [task])
        return task_payload(task, community_names(db, [task.community_id]).get(task.community_id, ""), users.get(task.claimed_by, ""))

    @app.get("/api/v1/admin/tasks")
    def admin_list_tasks(
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = Query(default=24, ge=1, le=100),
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
    ):
        require_admin(actor)
        stmt = select(Task).where(Task.is_qa.is_(False))
        if status:
            stmt = stmt.where(Task.status == status)
        items, next_cursor = paginated_items(db, stmt, Task, cursor, limit)
        names = community_names(db, [item.community_id for item in items])
        users = task_users(db, items)
        return {
            "items": [task_payload(item, names.get(item.community_id, ""), users.get(item.claimed_by, "")) for item in items],
            "next_cursor": next_cursor,
        }

    # ---- 定点投喂 ------------------------------------------------------

    @app.get("/api/v1/public/feeding-stats")
    def public_feeding_stats(db: DbSession = Depends(db_session)):
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

    @app.get("/api/v1/feeding-points")
    def list_feeding_points(
        cursor: Optional[str] = None,
        limit: int = Query(default=24, ge=1, le=100),
        lat: Optional[float] = Query(default=None, ge=-90, le=90),
        lng: Optional[float] = Query(default=None, ge=-180, le=180),
        sort: Optional[str] = None,
        actor=Depends(optional_user),
        db: DbSession = Depends(db_session),
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

    @app.post("/api/v1/feeding-points/{point_id}/logs", status_code=201)
    def create_feeding_log(
        point_id: str,
        payload: FeedingLogCreate,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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
        return feeding_log_payload(item, point.name)

    @app.get("/api/v1/feeding-logs/mine")
    def list_my_feeding_logs(
        cursor: Optional[str] = None,
        limit: int = Query(default=24, ge=1, le=100),
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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

    @app.get("/api/v1/feeding-logs/mine/summary")
    def my_feeding_summary(actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/admin/feeding-points", status_code=201)
    def create_feeding_point(payload: FeedingPointCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
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

    @app.patch("/api/v1/admin/feeding-points/{point_id}")
    def edit_feeding_point(
        point_id: str,
        payload: FeedingPointEdit,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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

    @app.get("/api/v1/admin/feeding-points")
    def admin_list_feeding_points(
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = Query(default=24, ge=1, le=100),
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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

    @app.get("/api/v1/cats/{cat_id}/events")
    def list_cat_events(cat_id: str, db: DbSession = Depends(db_session)):
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

    @app.post("/api/v1/admin/cats/{cat_id}/events", status_code=201)
    def create_cat_event(
        cat_id: str,
        payload: CatEventCreate,
        actor=Depends(current_user),
        db: DbSession = Depends(db_session),
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

    @app.post("/api/v1/media/images", status_code=201)
    async def upload_image(file: UploadFile = File(...), actor=Depends(current_user), db: DbSession = Depends(db_session)):
        allowed_content_types = {item[0] for item in PUBLIC_IMAGE_FORMATS.values()}
        if file.content_type not in allowed_content_types:
            error(415, "unsupported_image_type")
        content = await file.read(settings.max_image_bytes + 1)
        if len(content) > settings.max_image_bytes:
            error(413, "image_too_large")
        sanitized, content_type, extension = sanitize_public_image(
            content, file.content_type, settings.max_image_pixels, settings.max_image_bytes,
        )
        asset = MediaAsset(object_key=new_id() + extension, content_type=content_type, byte_size=len(sanitized), created_by=actor[0])
        target = settings.storage_root / asset.object_key
        target.write_bytes(sanitized)
        try:
            create_media_thumbnail(target, media_thumbnail_path(settings.storage_root, asset.object_key))
        except OSError:
            target.unlink(missing_ok=True)
            error(500, "thumbnail_generation_failed")
        db.add(asset)
        db.flush()
        audit(db, actor[0], "UPLOAD", "media", asset.id, after={"content_type": asset.content_type, "byte_size": asset.byte_size})
        db.commit()
        return {"id": asset.id, "object_key": asset.object_key, "content_type": asset.content_type, "byte_size": asset.byte_size}

    @app.get("/api/v1/media/{asset_id}")
    def get_media(asset_id: str, variant: str = Query(default="original", pattern="^(original|thumb)$"), db: DbSession = Depends(db_session)):
        asset = db.get(MediaAsset, asset_id)
        if not asset:
            error(404, "media_not_found")
        path = settings.storage_root / asset.object_key
        if not path.is_file():
            error(404, "media_file_not_found")
        if variant == "thumb":
            thumbnail_path = media_thumbnail_path(settings.storage_root, asset.object_key)
            if not thumbnail_path.is_file():
                try:
                    create_media_thumbnail(path, thumbnail_path)
                except OSError:
                    error(500, "thumbnail_generation_failed")
            return FileResponse(thumbnail_path, media_type="image/webp", headers=MEDIA_CACHE_HEADERS)
        return FileResponse(path, media_type=asset.content_type, headers=MEDIA_CACHE_HEADERS)

    return app


app = create_app()
