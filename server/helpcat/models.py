import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id():
    return uuid.uuid4().hex


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(80), unique=True, index=True, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="USER")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    nickname: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Session(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Community(Base):
    __tablename__ = "communities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    city: Mapped[str] = mapped_column(String(40), default="杭州市")
    district: Mapped[str] = mapped_column(String(40), default="富阳区")
    street: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_REVIEW", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Cat(Base):
    __tablename__ = "cats"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    community_id: Mapped[str] = mapped_column(ForeignKey("communities.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(80))
    living_status: Mapped[str] = mapped_column(String(80), default="")
    health_status: Mapped[str] = mapped_column(String(80), default="UNKNOWN")
    location_note: Mapped[str] = mapped_column(String(240))
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    photo_asset_id: Mapped[Optional[str]] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING_REVIEW", index=True)
    visibility_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DailyCatQuota(Base):
    __tablename__ = "daily_cat_quotas"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    quota_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    object_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(80))
    byte_size: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40))
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    community_id: Mapped[Optional[str]] = mapped_column(ForeignKey("communities.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    claimed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
