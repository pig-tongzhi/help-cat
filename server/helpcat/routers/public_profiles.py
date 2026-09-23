"""公开猫咪档案。"""

from ..dependencies import get_db
from ..errors import error
from ..models import Cat, Community
from ..serializers import cat_payload, normalized_profile_key
from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession


router = APIRouter()


@router.get("/api/v1/public/profiles/{profile_key}")
def public_profile(profile_key: str, db: DbSession = Depends(get_db)):
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
