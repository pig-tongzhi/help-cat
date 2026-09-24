from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Literal, Optional


class WechatLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    role: str = "USER"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)


class PasswordLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)
    # 勾了「记住这台设备」就签发长期会话（默认 90 天），否则用常规 30 天。
    remember: bool = False


class SessionRevokeRequest(BaseModel):
    # 会话 id 用令牌前 8 位表示：既够唯一，又不会把完整令牌发给前端。
    id: str = Field(min_length=8, max_length=16)


class CommunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    street: str = Field(min_length=1, max_length=80)


class CommunityEdit(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    street: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)
    version: int = Field(ge=1)


class CommunityReview(BaseModel):
    action: Optional[Literal["approve", "request_changes", "reject"]] = None
    note: str = Field(default="", max_length=500)
    version: Optional[int] = Field(default=None, ge=1)
    approved: Optional[bool] = None

    @model_validator(mode="after")
    def support_explicit_and_legacy_review(self):
        if self.action is None and self.approved is None:
            raise ValueError("community_review_action_required")
        if self.action is not None and self.approved is not None:
            raise ValueError("one_community_review_action_required")
        if self.action is not None and self.version is None:
            raise ValueError("community_version_required")
        if self.action is None:
            self.action = "approve" if self.approved else "reject"
            if not self.approved and not self.note:
                self.note = "旧版审核驳回"
        return self


class CommunityMerge(BaseModel):
    target_community_id: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=1)


class CommunityArchive(BaseModel):
    version: int = Field(ge=1)


class CatCommunityReassign(BaseModel):
    community_id: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=1)


class CatAdminEdit(BaseModel):
    """Partial edit of one existing cat; every field is optional but at least one must be sent.

    The allowed `health_status` values are the ones the app already renders for cats
    (H5 `healthLabel`/`healthTone` and the miniprogram `HEALTH_LABELS`).
    """

    nickname: Optional[str] = Field(default=None, min_length=1, max_length=80)
    health_status: Optional[Literal["HEALTHY", "NEEDS_HELP", "UNKNOWN"]] = None
    living_status: Optional[str] = Field(default=None, max_length=80)
    location_note: Optional[str] = Field(default=None, max_length=240)
    # Sending photo_asset_id as null detaches the current photo; omitting the field leaves it untouched.
    photo_asset_id: Optional[str] = Field(default=None, max_length=32)
    # Optimistic lock: when sent it must equal the cat's current version.
    version: Optional[int] = Field(default=None, ge=1)

    @field_validator("nickname", "living_status", "location_note")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_at_least_one_edit(self):
        if not self.model_fields_set:
            raise ValueError("empty_cat_edit")
        if self.nickname is not None and not 1 <= len(self.nickname) <= 80:
            raise ValueError("invalid_cat_nickname")
        if self.location_note is not None and len(self.location_note) > 240:
            raise ValueError("invalid_cat_location_note")
        return self


class BatchReviewItem(BaseModel):
    """后台批量审核里的一条：带上版本号，避免用过期页面覆盖别人的改动。"""

    id: str = Field(min_length=1, max_length=32)
    version: Optional[int] = Field(default=None, ge=1)
    note: str = Field(default="", max_length=500)


class BatchReviewRequest(BaseModel):
    cats: List[BatchReviewItem] = Field(default_factory=list)
    communities: List[BatchReviewItem] = Field(default_factory=list)
    include_communities: bool = True
    max_items: int = Field(default=200, exclude=True)

    @model_validator(mode="after")
    def require_something_and_cap_the_batch(self):
        if not self.cats and not self.communities:
            raise ValueError("empty_batch")
        if len(self.cats) + len(self.communities) > self.max_items:
            raise ValueError("batch_too_large")
        return self


class ReviewRequest(BaseModel):
    approved: bool


class CommunityCandidateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    street: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


class CatCreate(BaseModel):
    community_id: Optional[str] = None
    community_candidate: Optional[CommunityCandidateCreate] = None
    nickname: str = Field(min_length=1, max_length=80)
    location_note: str = Field(min_length=1, max_length=240)
    living_status: str = Field(default="", max_length=80)
    health_status: str = Field(default="UNKNOWN", max_length=80)
    photo_asset_id: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def require_one_community_source(self):
        if bool(self.community_id) == bool(self.community_candidate):
            raise ValueError("exactly_one_community_source_required")
        return self


class VisibilityRequest(BaseModel):
    visible: bool


class RoleUpdate(BaseModel):
    role: Literal["USER", "ADMIN"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    community_id: Optional[str] = None


class ImpactEventCreate(BaseModel):
    kind: Literal["RESCUED", "ADOPTED", "MEDICAL", "SUPPORTER"]
    amount: int = Field(default=1, ge=1, le=1000000)
    note: str = Field(default="", max_length=1000)
    occurred_at: Optional[datetime] = None


class LeadMessageCreate(BaseModel):
    """A contact left by a visitor on the public welcome page."""

    name: str = Field(default="", max_length=80)
    contact_type: Literal["WECHAT", "PHONE", "QQ", "OTHER"] = "WECHAT"
    contact: str = Field(min_length=2, max_length=120)
    message: str = Field(default="", max_length=1000)
    source: str = Field(default="", max_length=80)

    @field_validator("name", "contact", "message", "source")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_real_contact(self):
        if len(self.contact) < 2:
            raise ValueError("contact_required")
        return self


class LeadMessageStatusUpdate(BaseModel):
    status: Literal["NEW", "CONTACTED", "CLOSED"]
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str) -> str:
        return value.strip()


class FeedingPointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    community_id: Optional[str] = Field(default=None, max_length=32)
    location_note: str = Field(default="", max_length=240)
    feeding_time: str = Field(default="", max_length=80)
    caretaker_note: str = Field(default="", max_length=1000)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class FeedingPointEdit(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    location_note: Optional[str] = Field(default=None, max_length=240)
    feeding_time: Optional[str] = Field(default=None, max_length=80)
    caretaker_note: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[Literal["ACTIVE", "PAUSED", "ARCHIVED"]] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class FeedingLogCreate(BaseModel):
    food_note: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)
    photo_asset_id: Optional[str] = Field(default=None, max_length=32)


class FeedingShiftClaim(BaseModel):
    """One volunteer claiming the feeding duty for a point on one day."""

    shift_date: str = Field(min_length=10, max_length=10)
    note: str = Field(default="", max_length=200)

    @field_validator("shift_date")
    @classmethod
    def require_iso_calendar_date(cls, value: str) -> str:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except (TypeError, ValueError):
            raise ValueError("invalid_shift_date")


class TaskComplete(BaseModel):
    note: str = Field(default="", max_length=1000)
    evidence_asset_id: Optional[str] = Field(default=None, max_length=32)


class TaskCancel(BaseModel):
    reason: str = Field(default="", max_length=500)


class TaskReassign(BaseModel):
    target_user_id: Optional[str] = Field(default=None, max_length=32)


class CatEventCreate(BaseModel):
    kind: Literal["RESCUE", "FEED", "MEDICAL", "CHECKUP", "ADOPTED", "NOTE"]
    title: str = Field(min_length=1, max_length=120)
    detail: str = Field(default="", max_length=2000)
    occurred_at: Optional[datetime] = None
