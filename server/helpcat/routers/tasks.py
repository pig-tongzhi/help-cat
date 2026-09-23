"""救助任务。"""

from ..auth import require_admin
from ..dependencies import get_current_user, get_db
from ..errors import error
from ..models import Community, MediaAsset, Task, User
from ..pagination import paginated_items
from ..schemas import TaskCancel, TaskComplete, TaskCreate, TaskReassign
from ..serializers import audit, community_names, is_qa_label, task_payload
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from typing import Optional


router = APIRouter()


@router.post("/api/v1/tasks", status_code=201)
def create_task(payload: TaskCreate, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    if payload.community_id and not db.get(Community, payload.community_id):
        error(404, "community_not_found")
    task = Task(title=payload.title.strip(), description=payload.description.strip(), community_id=payload.community_id, created_by=actor[0], is_qa=is_qa_label(payload.title))
    db.add(task)
    db.flush()
    audit(db, actor[0], "CREATE", "task", task.id, after={"title": task.title, "status": task.status})
    db.commit()
    return task_payload(task)


@router.get("/api/v1/tasks")
def list_tasks(cursor: Optional[str] = None, limit: int = Query(default=24, ge=1, le=100), db: DbSession = Depends(get_db)):
    items, next_cursor = paginated_items(db, select(Task).where(Task.status == "OPEN", Task.is_qa.is_(False)), Task, cursor, limit)
    return {"items": [task_payload(item) for item in items], "next_cursor": next_cursor}


@router.post("/api/v1/tasks/{task_id}/claim")
def claim_task(task_id: str, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
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


@router.get("/api/v1/tasks/mine")
def list_my_tasks(
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
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


@router.post("/api/v1/tasks/{task_id}/complete")
def complete_task(
    task_id: str,
    payload: TaskComplete,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
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


@router.post("/api/v1/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    payload: TaskCancel,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
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


@router.post("/api/v1/tasks/{task_id}/reassign")
def reassign_task(
    task_id: str,
    payload: TaskReassign,
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
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


@router.get("/api/v1/admin/tasks")
def admin_list_tasks(
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=24, ge=1, le=100),
    actor=Depends(get_current_user),
    db: DbSession = Depends(get_db),
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
