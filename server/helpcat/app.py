import json
import mimetypes
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from .auth import DUMMY_PASSWORD_HASH, WechatProvider, current_user_factory, hash_password, issue_session, require_admin, require_super_admin, verify_password
from .config import Settings
from .db import Base, ensure_schema, make_session_factory
from .models import AuditLog, Cat, Community, DailyCatQuota, MediaAsset, Session as AuthSession, Task, User, new_id
from .schemas import CatCreate, CommunityCreate, PasswordLoginRequest, RegisterRequest, ReviewRequest, RoleUpdate, TaskCreate, VisibilityRequest, WechatLoginRequest


def error(status, code, message=None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message or code})


def cat_payload(cat):
    return {"id": cat.id, "community_id": cat.community_id, "code": cat.code, "nickname": cat.nickname,
            "living_status": cat.living_status, "health_status": cat.health_status, "location_note": cat.location_note,
            "review_status": cat.review_status, "visibility_status": cat.visibility_status, "created_by": cat.created_by,
            "photo_asset_id": cat.photo_asset_id, "latitude": cat.latitude, "longitude": cat.longitude}


def community_payload(item):
    return {"id": item.id, "city": item.city, "district": item.district, "street": item.street, "name": item.name, "status": item.status, "created_by": item.created_by}


def task_payload(item):
    return {"id": item.id, "title": item.title, "description": item.description, "community_id": item.community_id,
            "status": item.status, "created_by": item.created_by, "claimed_by": item.claimed_by}


def user_payload(user):
    return {"id": user.id, "username": user.username, "nickname": user.nickname, "role": user.role,
            "status": user.status, "created_at": user.created_at.isoformat()}


def audit(db, actor_id, action, entity_type, entity_id, before=None, after=None):
    db.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                    before_json=json.dumps(before or {}, ensure_ascii=False), after_json=json.dumps(after or {}, ensure_ascii=False)))


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
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins or ["http://localhost"], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
    current_user = current_user_factory(session_factory, settings)

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
    def list_communities(q: str = "", db: DbSession = Depends(db_session)):
        items = db.scalars(select(Community).where(Community.status == "ACTIVE", Community.name.contains(q)).order_by(Community.name)).all()
        return {"items": [community_payload(item) for item in items]}

    @app.get("/api/v1/admin/communities")
    def list_admin_communities(actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        items = db.scalars(select(Community).order_by(Community.updated_at.desc())).all()
        return {"items": [community_payload(item) for item in items]}

    @app.get("/api/v1/admin/users")
    def list_admin_users(actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_super_admin(actor)
        items = db.scalars(select(User).order_by(User.created_at)).all()
        return {"items": [user_payload(item) for item in items]}

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
        duplicate = db.scalar(select(Community).where(Community.name == payload.name, Community.status != "ARCHIVED"))
        if duplicate:
            error(409, "community_exists")
        item = Community(name=payload.name.strip(), street=payload.street.strip(), status="ACTIVE" if role in {"ADMIN", "SUPER_ADMIN"} else "PENDING_REVIEW", created_by=actor_id)
        db.add(item)
        db.flush()
        audit(db, actor_id, "CREATE", "community", item.id, after=community_payload(item))
        db.commit()
        return community_payload(item)

    @app.patch("/api/v1/communities/{community_id}")
    def edit_community(community_id: str, payload: CommunityCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        item = db.get(Community, community_id)
        if not item:
            error(404, "community_not_found")
        before = community_payload(item)
        item.name = payload.name.strip()
        item.street = payload.street.strip()
        audit(db, actor[0], "UPDATE", "community", item.id, before, community_payload(item))
        db.commit()
        return community_payload(item)

    @app.post("/api/v1/communities/{community_id}/archive")
    def archive_community(community_id: str, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        item = db.get(Community, community_id)
        if not item:
            error(404, "community_not_found")
        before = {"status": item.status}
        item.status = "ARCHIVED"
        audit(db, actor[0], "ARCHIVE", "community", item.id, before, {"status": item.status})
        db.commit()
        return community_payload(item)

    @app.post("/api/v1/communities/{community_id}/review")
    def review_community(community_id: str, payload: ReviewRequest, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        item = db.get(Community, community_id)
        if not item:
            error(404, "community_not_found")
        before = {"status": item.status}
        item.status = "ACTIVE" if payload.approved else "HIDDEN"
        item.reviewed_by = actor[0]
        audit(db, actor[0], "REVIEW", "community", item.id, before, {"status": item.status})
        db.commit()
        return community_payload(item)

    @app.get("/api/v1/cats")
    def list_cats(q: str = "", community_id: Optional[str] = None, authorization: Optional[str] = Header(default=None), db: DbSession = Depends(db_session)):
        is_admin = False
        if authorization and authorization.startswith("Bearer "):
            session = db.scalar(select(AuthSession).where(AuthSession.token == authorization[7:].strip()))
            if session:
                user = db.get(User, session.user_id)
                expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
                is_admin = bool(user and user.role in {"ADMIN", "SUPER_ADMIN"} and user.status == "ACTIVE" and expires_at >= datetime.now(timezone.utc))
        stmt = select(Cat)
        if not is_admin:
            stmt = stmt.where(Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE")
        if community_id:
            stmt = stmt.where(Cat.community_id == community_id)
        if q:
            stmt = stmt.where(Cat.nickname.contains(q) | Cat.code.contains(q))
        items = db.scalars(stmt.order_by(Cat.created_at.desc())).all()
        return {"items": [cat_payload(item) for item in items]}

    @app.post("/api/v1/cats", status_code=201)
    def create_cat(payload: CatCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        actor_id, role = actor
        community = db.get(Community, payload.community_id)
        if not community or community.status != "ACTIVE":
            error(404, "community_not_found")
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
        photo_asset = None
        if payload.photo_asset_id:
            photo_asset = db.get(MediaAsset, payload.photo_asset_id)
            if not photo_asset or photo_asset.created_by != actor_id:
                error(403, "photo_asset_forbidden")
        review_status = "APPROVED" if role in {"ADMIN", "SUPER_ADMIN"} else "PENDING_REVIEW"
        cat = Cat(community_id=community.id, code="HC-" + secrets.token_hex(4).upper(), nickname=payload.nickname.strip(),
                  living_status=payload.living_status.strip(), health_status=payload.health_status.strip(), location_note=payload.location_note.strip(),
                  latitude=payload.latitude, longitude=payload.longitude,
                  review_status=review_status, created_by=actor_id,
                  photo_asset_id=photo_asset.id if photo_asset else None)
        db.add(cat)
        db.flush()
        audit(db, actor_id, "CREATE", "cat", cat.id, after=cat_payload(cat))
        db.commit()
        return cat_payload(cat)

    def get_cat_or_404(db, cat_id):
        cat = db.get(Cat, cat_id)
        if not cat:
            error(404, "cat_not_found")
        return cat

    @app.post("/api/v1/cats/{cat_id}/review")
    def review_cat(cat_id: str, payload: ReviewRequest, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        cat = get_cat_or_404(db, cat_id)
        before = {"review_status": cat.review_status}
        cat.review_status = "APPROVED" if payload.approved else "REJECTED"
        audit(db, actor[0], "REVIEW", "cat", cat.id, before, {"review_status": cat.review_status})
        db.commit()
        return cat_payload(cat)

    @app.post("/api/v1/cats/{cat_id}/visibility")
    def set_visibility(cat_id: str, payload: VisibilityRequest, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        cat = get_cat_or_404(db, cat_id)
        before = {"visibility_status": cat.visibility_status}
        cat.visibility_status = "ACTIVE" if payload.visible else "HIDDEN"
        audit(db, actor[0], "VISIBILITY", "cat", cat.id, before, {"visibility_status": cat.visibility_status})
        db.commit()
        return cat_payload(cat)

    @app.post("/api/v1/cats/{cat_id}/archive")
    def archive_cat(cat_id: str, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        cat = get_cat_or_404(db, cat_id)
        before = {"visibility_status": cat.visibility_status}
        cat.visibility_status = "ARCHIVED"
        audit(db, actor[0], "ARCHIVE", "cat", cat.id, before, {"visibility_status": cat.visibility_status})
        db.commit()
        return cat_payload(cat)

    @app.get("/api/v1/me/submissions")
    def my_submissions(actor=Depends(current_user), db: DbSession = Depends(db_session)):
        cats = db.scalars(select(Cat).where(Cat.created_by == actor[0]).order_by(Cat.created_at.desc())).all()
        communities = db.scalars(select(Community).where(Community.created_by == actor[0]).order_by(Community.created_at.desc())).all()
        return {"cats": [cat_payload(item) for item in cats], "communities": [community_payload(item) for item in communities]}

    @app.post("/api/v1/tasks", status_code=201)
    def create_task(payload: TaskCreate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
        require_admin(actor)
        if payload.community_id and not db.get(Community, payload.community_id):
            error(404, "community_not_found")
        task = Task(title=payload.title.strip(), description=payload.description.strip(), community_id=payload.community_id, created_by=actor[0])
        db.add(task)
        db.flush()
        audit(db, actor[0], "CREATE", "task", task.id, after={"title": task.title, "status": task.status})
        db.commit()
        return task_payload(task)

    @app.get("/api/v1/tasks")
    def list_tasks(db: DbSession = Depends(db_session)):
        items = db.scalars(select(Task).where(Task.status == "OPEN").order_by(Task.created_at.desc())).all()
        return {"items": [task_payload(item) for item in items]}

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

    @app.post("/api/v1/media/images", status_code=201)
    async def upload_image(file: UploadFile = File(...), actor=Depends(current_user), db: DbSession = Depends(db_session)):
        allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
        if file.content_type not in allowed:
            error(415, "unsupported_image_type")
        content = await file.read(settings.max_image_bytes + 1)
        if len(content) > settings.max_image_bytes:
            error(413, "image_too_large")
        signatures = {"image/jpeg": lambda value: value.startswith(b"\xff\xd8\xff"), "image/png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"), "image/webp": lambda value: value.startswith(b"RIFF") and value[8:12] == b"WEBP"}
        if not signatures[file.content_type](content):
            error(415, "image_content_mismatch")
        asset = MediaAsset(object_key=new_id() + allowed[file.content_type], content_type=file.content_type, byte_size=len(content), created_by=actor[0])
        target = settings.storage_root / asset.object_key
        target.write_bytes(content)
        db.add(asset)
        db.flush()
        audit(db, actor[0], "UPLOAD", "media", asset.id, after={"content_type": asset.content_type, "byte_size": asset.byte_size})
        db.commit()
        return {"id": asset.id, "object_key": asset.object_key, "content_type": asset.content_type, "byte_size": asset.byte_size}

    @app.get("/api/v1/media/{asset_id}")
    def get_media(asset_id: str, db: DbSession = Depends(db_session)):
        asset = db.get(MediaAsset, asset_id)
        if not asset:
            error(404, "media_not_found")
        path = settings.storage_root / asset.object_key
        if not path.is_file():
            error(404, "media_file_not_found")
        return FileResponse(path, media_type=asset.content_type)

    return app


app = create_app()
