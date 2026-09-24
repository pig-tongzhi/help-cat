"""登录、注册与会话。"""

import json

from ..auth import DUMMY_PASSWORD_HASH, hash_password, issue_session, verify_password
from .. import login_guard
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import AuditLog, Session as AuthSession, User
from ..schemas import PasswordLoginRequest, RegisterRequest, SessionRevokeRequest, WechatLoginRequest
from ..serializers import audit, auth_payload, session_device_label
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from fastapi import Depends, Header, Request, Response
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
def register(request: Request, response: Response, payload: RegisterRequest, db: DbSession = Depends(get_db)):
    username = payload.username.strip()
    if db.scalar(select(User).where(User.username == username)):
        error(409, "username_exists")
    user = User(openid="local:" + username, username=username, password_hash=hash_password(payload.password), role="USER", nickname=username)
    db.add(user)
    db.flush()
    days = request.app.state.settings.session_days
    result = auth_payload(db, user, days)
    db.commit()
    _set_session_cookie(response, request, result["access_token"], days)
    return result


@router.post("/api/v1/auth/login")
def password_login(request: Request, response: Response, payload: PasswordLoginRequest, db: DbSession = Depends(get_db)):
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
    # 勾了「记住这台设备」就签长期会话；设备信息写进审计，供「登录的设备」列表使用
    days = settings.session_days_remember if payload.remember else settings.session_days
    result = auth_payload(db, user, days, audit_meta={
        "user_agent": request.headers.get("user-agent", ""),
        "ip": client_ip,
        "remember": payload.remember,
    })
    db.commit()
    _set_session_cookie(response, request, result["access_token"], days)
    return result


COOKIE_NAME = "helpcat_session"


def _set_session_cookie(response: Response, request: Request, token: str, days: int) -> None:
    """把会话也写进 HttpOnly Cookie。

    为什么需要它：微信内置浏览器（以及 iOS 的 Safari 内核）会清掉页面 JS 写入的存储，
    令牌放 localStorage 就会出现"退出微信再进来又要登录"。Cookie 由浏览器网络层管理，
    不受这个影响；HttpOnly 还让 XSS 偷不走它。Secure 只在真的走 HTTPS 时才加，
    免得本地 HTTP 调试时 Cookie 直接被丢掉。
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=days * 86400,
        httponly=True, secure=(scheme == "https"), samesite="lax", path="/",
    )


def _session_rows(db: DbSession, user_id: str):
    """把会话和它们的签发审计拼在一起。

    不走 schema 变更：会话表只有 token/expires_at/revoked_at，设备/登录时间/IP 都在
    SESSION_ISSUE 审计里，用令牌前 8 位对齐。找不到审计的（升级前签发的旧会话）
    就按 expires_at 反推签发时间，并标成"未知设备"，而不是把它藏起来。
    """
    sessions = db.scalars(select(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > datetime.now(timezone.utc),
    ).order_by(AuthSession.expires_at.desc())).all()
    prefixes = [item.token[:8] for item in sessions]
    meta = {}
    if prefixes:
        rows = db.scalars(select(AuditLog).where(
            AuditLog.action == "SESSION_ISSUE", AuditLog.entity_id.in_(prefixes),
        ).order_by(AuditLog.created_at.asc())).all()
        for row in rows:
            try:
                payload = json.loads(row.after_json or "{}")
            except ValueError:
                payload = {}
            # 同一前缀可能有多条（重复签发），保留最新一条
            meta[row.entity_id] = {"device": payload.get("device") or "未知设备",
                                   "ip": payload.get("ip") or "",
                                   "days": payload.get("days") or 0,
                                   "remember": bool(payload.get("remember")),
                                   "created_at": row.created_at}
    return sessions, meta


@router.get("/api/v1/auth/sessions")
def list_sessions(request: Request, authorization: Optional[str] = Header(default=None),
                  actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    """当前账号还登录着哪些设备（含本机）。

    只返回自己名下的会话，且只给令牌前 8 位做标识 —— 完整令牌不发给前端。
    """
    current = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    sessions, meta = _session_rows(db, actor[0])
    items = []
    for item in sessions:
        prefix = item.token[:8]
        extra = meta.get(prefix, {})
        expires_at = item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at
        created_at = extra.get("created_at")
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at is None:
            created_at = expires_at - timedelta(days=extra.get("days") or request.app.state.settings.session_days)
        items.append({
            "id": prefix,
            "device": extra.get("device") or "未知设备（升级前签发）",
            "ip": extra.get("ip") or "",
            "remember": bool(extra.get("remember")),
            "current": bool(current) and item.token == current,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        })
    return {"items": items}


@router.post("/api/v1/auth/sessions/revoke")
def revoke_session(payload: SessionRevokeRequest, authorization: Optional[str] = Header(default=None),
                   actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    """把某一台设备踢下线。

    只能撤销自己名下的；本机要走 logout，避免"刚踢完自己又不用重新登录"的混乱。
    撤销是服务端的（revoked_at），所以那台设备上的令牌立刻失效。
    """
    current = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    sessions, _ = _session_rows(db, actor[0])
    target = next((item for item in sessions if item.token[:8] == payload.id), None)
    if target is None:
        error(404, "session_not_found")
    if target.token == current:
        error(400, "cannot_revoke_current_session")
    target.revoked_at = datetime.now(timezone.utc)
    audit(db, actor[0], "SESSION_REVOKE", "session", target.token[:8],
          after={"device": session_device_label(None)})
    db.commit()
    return {"revoked": target.token[:8]}


@router.post("/api/v1/auth/logout")
def logout(response: Response, actor=Depends(get_current_user), authorization: Optional[str] = Header(default=None), db: DbSession = Depends(get_db)):
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    session = db.get(AuthSession, token)
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/api/v1/auth/me")
def auth_me(actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    user = db.get(User, actor[0])
    return {"id": user.id, "username": user.username, "role": user.role}
