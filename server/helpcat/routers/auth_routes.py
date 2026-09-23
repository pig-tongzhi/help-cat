"""登录、注册与会话。"""

from ..auth import DUMMY_PASSWORD_HASH, hash_password, issue_session, verify_password
from .. import login_guard
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import Session as AuthSession, User
from ..schemas import PasswordLoginRequest, RegisterRequest, WechatLoginRequest
from ..serializers import auth_payload
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from typing import Optional


router = APIRouter()


@router.post("/api/v1/auth/wechat-login")
def wechat_login(request: Request, payload: WechatLoginRequest, db: DbSession = Depends(get_db)):
    openid = request.app.state.wechat_provider.exchange_code(payload.code)
    user = db.scalar(select(User).where(User.openid == openid))
    if not user:
        role = "ADMIN" if openid in request.app.state.settings.fake_admin_openids else "USER"
        user = User(openid=openid, role=role, nickname="")
        db.add(user)
        db.flush()
    user.last_login_at = datetime.now(timezone.utc)
    token = issue_session(db, user, request.app.state.settings.session_days)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "role": user.role}}

@router.post("/api/v1/auth/register", status_code=201)
def register(request: Request, payload: RegisterRequest, db: DbSession = Depends(get_db)):
    username = payload.username.strip()
    if db.scalar(select(User).where(User.username == username)):
        error(409, "username_exists")
    user = User(openid="local:" + username, username=username, password_hash=hash_password(payload.password), role="USER", nickname=username)
    db.add(user)
    db.flush()
    result = auth_payload(db, user, request.app.state.settings.session_days)
    db.commit()
    return result


@router.post("/api/v1/auth/login")
def password_login(request: Request, payload: PasswordLoginRequest, db: DbSession = Depends(get_db)):
    settings = request.app.state.settings
    username = payload.username.strip()
    client_ip = request.client.host if request.client else ""
    # 先看限速：同一账号 / 同一 IP 在窗口内失败太多就直接拒绝（原来完全没有限制）。
    login_guard.check(db, username, client_ip, settings)

    user = db.scalar(select(User).where(User.username == username))
    candidate_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    if not verify_password(payload.password, candidate_hash):
        login_guard.record_failure(db, username, client_ip)
        login_guard.prune(db, settings)
        db.commit()
        error(401, "invalid_credentials")
    if user.status != "ACTIVE":
        error(403, "user_disabled")
    login_guard.clear(db, username, client_ip)
    user.last_login_at = datetime.now(timezone.utc)
    result = auth_payload(db, user, settings.session_days)
    db.commit()
    return result


@router.post("/api/v1/auth/logout")
def logout(actor=Depends(get_current_user), authorization: Optional[str] = Header(default=None), db: DbSession = Depends(get_db)):
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    session = db.get(AuthSession, token)
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"status": "ok"}


@router.get("/api/v1/auth/me")
def auth_me(actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    user = db.get(User, actor[0])
    return {"id": user.id, "username": user.username, "role": user.role}
