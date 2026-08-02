from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional


class WechatLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    role: str = "USER"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)


class PasswordLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class CommunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    street: str = Field(min_length=1, max_length=80)


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
