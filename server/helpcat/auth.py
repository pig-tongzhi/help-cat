import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .config import Settings
from .models import Session, User


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240000)
    return "pbkdf2_sha256$240000$%s$%s" % (salt.hex(), digest.hex())


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


DUMMY_PASSWORD_HASH = hash_password("help-cat-invalid-password")


class WechatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def exchange_code(self, code: str) -> str:
        if code.startswith("fake:"):
            return code[5:]
        if not self.settings.wechat_app_id or not self.settings.wechat_app_secret:
            raise HTTPException(status_code=503, detail={"code": "wechat_not_configured"})
        raise HTTPException(status_code=501, detail={"code": "wechat_provider_pending"})


def issue_session(db: DbSession, user: User, days: int) -> str:
    token = secrets.token_urlsafe(48)
    db.add(Session(token=token, user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=days)))
    return token


def current_user_factory(session_factory, settings: Settings):
    def current_user(authorization: Optional[str] = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})
        token = authorization[7:].strip()
        with session_factory() as db:
            session = db.scalar(select(Session).where(Session.token == token))
            expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session and session.expires_at.tzinfo is None else (session.expires_at if session else None)
            revoked_at = session.revoked_at.replace(tzinfo=timezone.utc) if session and session.revoked_at and session.revoked_at.tzinfo is None else (session.revoked_at if session else None)
            if not session or revoked_at or expires_at < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail={"code": "session_expired"})
            user = db.get(User, session.user_id)
            if not user or user.status != "ACTIVE":
                raise HTTPException(status_code=403, detail={"code": "user_disabled"})
            return user.id, user.role
    return current_user


def require_admin(current_user):
    if current_user[1] not in {"ADMIN", "SUPER_ADMIN"}:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return current_user


def require_super_admin(current_user):
    if current_user[1] != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail={"code": "super_admin_required"})
    return current_user
