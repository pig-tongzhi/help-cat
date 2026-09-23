"""后台批量审核。

单人管理员一条条点"审核通过"是当前最费时间的操作，而这个操作本身没有判断含量 ——
真正需要判断的是**要不要**通过，不是怎么点。所以这里提供一次通过多条的接口，
并且顺带解决"新小区 + 新猫咪"要连点两次的问题（`include_communities`）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from ..auth import require_admin
from ..dependencies import get_current_user, get_db
from ..reviews import batch_approve, pending_review_counts
from ..schemas import BatchReviewRequest

router = APIRouter()


@router.post("/api/v1/admin/reviews/approve")
def approve_many(payload: BatchReviewRequest, actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    return batch_approve(
        db, actor[0],
        [item.model_dump() for item in payload.cats],
        [item.model_dump() for item in payload.communities],
        include_communities=payload.include_communities,
    )


@router.get("/api/v1/admin/reviews/pending")
def pending_counts(actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    require_admin(actor)
    return pending_review_counts(db)
