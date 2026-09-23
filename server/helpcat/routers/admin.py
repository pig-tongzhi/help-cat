"""后台用户与角色。"""

from ..auth import require_super_admin
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import User
from ..pagination import paginated_items
from ..schemas import RoleUpdate
from ..serializers import audit, user_payload
from fastapi import APIRouter
from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from typing import Optional


router = APIRouter()


@router.get("/api/v1/admin/users")
def list_admin_users(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_super_admin(actor)
    items, next_cursor = paginated_items(db, select(User), User, cursor, limit)
    return {"items": [user_payload(item) for item in items], "next_cursor": next_cursor}


@router.post("/api/v1/admin/users/{user_id}/role")
def update_user_role(user_id: str, payload: RoleUpdate, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
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
