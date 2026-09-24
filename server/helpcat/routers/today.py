"""首页的「今天就一件事」与「本周小结」。

为什么单独做一个接口：首页原来只有静态文案加累计数字，而生产上累计值是 0，
看起来像没人用。访客真正需要的是"现在我能做什么"，这一条需要一个跨表聚合
（喂食点 / 值班 / 投喂记录 / 救助任务 / 成果事件 / 新档案），放在首页自己的接口里，
前端一次请求就能把两张卡渲染出来，不必串四个接口。

口径说明：
  * 日历日一律按 Asia/Shanghai（`shanghai_today()`），和投喂打卡、值班认领保持一致。
  * "本周" = 含今天在内的最近 7 天，和 `/public/feeding-stats` 用同一个窗口。
  * 所有查询都排除 `is_qa`（QA 数据是测试期留下的，不能进公开数字）。
"""
from datetime import datetime, time as day_time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from ..dependencies import get_db
from ..domain import shanghai_today
from ..models import Cat, FeedingLog, FeedingPoint, FeedingShift, ImpactEvent, Task

router = APIRouter()
SHANGHAI = ZoneInfo("Asia/Shanghai")

WEEK_KINDS = {"RESCUED": "rescued", "ADOPTED": "adopted", "MEDICAL": "medical"}


def _week_start(today: str) -> str:
    """最近 7 天的起点（含今天），与 feeding-stats 同一个口径。"""
    return (datetime.fromisoformat(today).date() - timedelta(days=6)).isoformat()


def _headline(db: DbSession, today: str) -> dict:
    points = db.scalars(select(FeedingPoint).where(
        FeedingPoint.is_qa.is_(False), FeedingPoint.status == "ACTIVE",
    )).all()
    if points:
        covered = set(db.scalars(select(FeedingShift.point_id).where(
            FeedingShift.is_qa.is_(False), FeedingShift.shift_date == today,
            FeedingShift.status != "CANCELLED",
        )).all())
        covered |= set(db.scalars(select(FeedingLog.point_id).where(
            FeedingLog.is_qa.is_(False), FeedingLog.fed_on == today,
        )).all())
        uncovered = [point for point in points if point.id not in covered]
        if uncovered:
            first = uncovered[0]
            return {
                "kind": "feeding_gap",
                "text": f"今天还有 {len(uncovered)} 个喂食点没人管",
                "detail": first.name + (f" · {first.feeding_time}" if first.feeding_time else ""),
                "action": "feeding",
                "action_label": "去认领今天的投喂",
            }
    open_tasks = db.scalar(select(func.count()).select_from(Task).where(
        Task.is_qa.is_(False), Task.status == "OPEN",
    )) or 0
    if open_tasks:
        return {
            "kind": "task_open",
            "text": f"有 {open_tasks} 件救助任务等人认领",
            "detail": "看看现在需要什么帮助，领一件你能做的",
            "action": "tasks",
            "action_label": "看看救助任务",
        }
    return {
        "kind": "quiet",
        "text": "今天的投喂都有人管了",
        "detail": "谢谢你。可以去看看社区里的猫，或者记录你遇见的那一只",
        "action": "cats",
        "action_label": "看看猫咪档案",
    }


def _week(db: DbSession, today: str) -> dict:
    week_start = _week_start(today)
    feeds = db.scalar(select(func.count()).select_from(FeedingLog).where(
        FeedingLog.is_qa.is_(False), FeedingLog.fed_on >= week_start,
    )) or 0
    since = datetime.combine(datetime.fromisoformat(week_start).date(), day_time.min, tzinfo=SHANGHAI)
    events = dict(db.execute(
        select(ImpactEvent.kind, func.sum(ImpactEvent.amount)).where(
            ImpactEvent.is_qa.is_(False), ImpactEvent.reversed_at.is_(None),
            ImpactEvent.occurred_at >= since,
        ).group_by(ImpactEvent.kind)
    ).all())
    new_cats = db.scalar(select(func.count()).select_from(Cat).where(
        Cat.is_qa.is_(False), Cat.created_at >= since,
        Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE",
    )) or 0
    return {
        "since": week_start,
        "feeding": feeds,
        "new_cats": new_cats,
        "rescued": events.get("RESCUED", 0),
        "adopted": events.get("ADOPTED", 0),
        "medical": events.get("MEDICAL", 0),
    }


@router.get("/api/v1/public/today")
def public_today(db: DbSession = Depends(get_db)):
    today = shanghai_today()
    return {"date": today, "headline": _headline(db, today), "week": _week(db, today)}
