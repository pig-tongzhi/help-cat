#!/usr/bin/env python3
"""Seed realistic, publicly visible demo data for Help Cat — and remove it again.

Unlike ``help_cat_qa_seed.py`` (which writes ``is_qa=1`` fixtures the public
pages filter out), every row here is ``is_qa=0``: approved cats, active feeding
points, feeding logs, shifts, cat timelines and impact events that a visitor
actually sees. The point is to make a freshly deployed site look lived-in.

Every row uses a fixed deterministic primary key prefixed with ``demo-``:

    demo-user-01  demo-community-01  demo-cat-01  demo-point-01
    demo-log-01-01  demo-event-01-01  demo-impact-01  demo-shift-01-01

Re-running is a no-op: an existing id is reported as skipped, never rewritten.
``--cleanup`` selects rows *only* by those ``demo-`` id prefixes, previews the
per-table counts, and deletes nothing until ``--execute`` is passed.

    python scripts/seed_demo_data.py --database-url sqlite:////path/to.db
    python scripts/seed_demo_data.py --database-url ... --cleanup
    python scripts/seed_demo_data.py --database-url ... --cleanup --execute
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))

from sqlalchemy import func, insert, select  # noqa: E402

from helpcat import models  # noqa: E402,F401 - registers every table on Base.metadata
from helpcat.community_rules import normalize_community_name  # noqa: E402
from helpcat.db import ensure_schema, make_session_factory  # noqa: E402
from helpcat.models import AuditLog, Cat, Community  # noqa: E402

DEMO_PREFIX = "demo-"
CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_CITY = "杭州市"
DEFAULT_DISTRICT = "富阳区"
DEFAULT_STREET = "银湖街道"
DEFAULT_DATABASE_ENV = "HELPCAT_DATABASE_URL"

# Every fixed id below must fit its column, which is String(32) throughout.
USER_IDS = ("demo-user-01", "demo-user-02", "demo-user-03")
DEMO_USERS: Tuple[Tuple[str, str], ...] = (
    (USER_IDS[0], "张阿姨"),
    (USER_IDS[1], "李叔"),
    (USER_IDS[2], "小雨"),
)
DEMO_OPENIDS = {"demo-user-01": "demo-openid-01", "demo-user-02": "demo-openid-02", "demo-user-03": "demo-openid-03"}
DEMO_USERNAMES = {"demo-user-01": "demo_zhang_ayi", "demo-user-02": "demo_li_shu", "demo-user-03": "demo_xiao_yu"}

COMMUNITY_IDS = ("demo-community-01", "demo-community-02", "demo-community-03")
DEMO_COMMUNITIES: Tuple[Tuple[str, str, str], ...] = (
    (COMMUNITY_IDS[0], "富云大苑", DEFAULT_STREET),
    (COMMUNITY_IDS[1], "上林湖花园", DEFAULT_STREET),
    (COMMUNITY_IDS[2], "银湖公寓", DEFAULT_STREET),
)

# (id, nickname, community_offset, location_note, health_status, living_status, notes)
DEMO_CATS: Tuple[Tuple[str, str, int, str, str, str, str], ...] = (
    ("demo-cat-01", "奶牛", 0, "3 幢北侧绿化带", "健康", "社区定居", "亲人的黑白猫，喜欢蹲在电动车棚顶。"),
    ("demo-cat-02", "三花", 0, "南门快递柜后面", "健康", "社区定居", "已绝育，耳朵有剪口标记。"),
    ("demo-cat-03", "橘座", 0, "中心花园长椅下", "偏胖", "社区定居", "见人就翻肚皮，投喂点常驻。"),
    ("demo-cat-04", "小黑", 1, "地下车库入口", "健康", "社区定居", "怕人，夜里才出来吃粮。"),
    ("demo-cat-05", "花卷", 1, "5 幢单元门口", "需要观察", "社区定居", "右前爪有旧伤，走路略跛。"),
    ("demo-cat-06", "芝麻", 1, "儿童乐园滑梯旁", "健康", "社区散养", "年纪小，常和花卷一起出现。"),
    ("demo-cat-07", "大黄", 2, "西门保安亭旁", "健康", "社区定居", "体型最大，会赶走外来公猫。"),
    ("demo-cat-08", "雪球", 2, "地下车库 B2 通风口", "健康", "社区散养", "全白长毛，胆子小。"),
    ("demo-cat-09", "煤球", 2, "垃圾房北侧墙根", "需要观察", "社区散养", "最近食欲一般，已安排复检。"),
    ("demo-cat-10", "小满", 0, "2 幢东侧灌木丛", "健康", "社区定居", "去年冬天在这里被救助，很黏人。"),
)

# (id, name, community_offset, location_note, feeding_time, caretaker_note, latitude, longitude)
DEMO_POINTS: Tuple[Tuple[str, str, int, str, str, str, float, float], ...] = (
    ("demo-point-01", "富云大苑北门投喂点", 0, "北门快递柜旁石板下", "每天 07:30", "请用干粮，旁边有清水盆。", 30.051200, 119.960300),
    ("demo-point-02", "上林湖花园中心花园点", 1, "中心花园凉亭西侧", "每天 18:00", "先换清水再放粮，碗请收回原处。", 30.055600, 119.965800),
    ("demo-point-03", "银湖公寓地库入口点", 2, "地下车库入口右侧墙角", "每天 21:00", "地库风大，喂完请压好防潮垫。", 30.047900, 119.955100),
    ("demo-point-04", "银湖街道沿河步道点", 0, "沿河步道第 3 张长椅后", "每天 06:50", "周末人多，请把粮放在长椅后。", 30.060400, 119.969900),
)

# (id, day_offset_from_today, point_offset, user_offset, food_note, note)
# The window is the last 10 days ending today (Asia/Shanghai): group 01 is
# today-9 and group 10 is today, so no check-in is ever dated in the future.
DEMO_LOGS: Tuple[Tuple[str, int, int, int, str, str], ...] = (
    ("demo-log-01-01", -9, 0, 0, "猫粮 200g + 换清水", "北门三只都在。"),
    ("demo-log-01-02", -9, 1, 1, "猫粮 150g", ""),
    ("demo-log-01-03", -9, 2, 2, "湿粮一罐 + 清水", "地库有点冷，加了纸箱。"),
    ("demo-log-01-04", -9, 3, 0, "猫粮 180g", ""),
    ("demo-log-02-01", -8, 1, 0, "猫粮 200g", ""),
    ("demo-log-02-02", -8, 2, 1, "猫粮 150g + 换清水", "橘座吃了一半。"),
    ("demo-log-02-03", -8, 3, 2, "猫粮 200g", ""),
    ("demo-log-02-04", -8, 0, 1, "猫粮 120g", "去得晚，碗已经空了。"),
    ("demo-log-03-01", -7, 2, 0, "猫粮 150g", ""),
    ("demo-log-03-02", -7, 3, 1, "猫粮 200g + 换清水", ""),
    ("demo-log-03-03", -7, 0, 2, "猫粮 200g", "小黑第一次当面吃粮。"),
    ("demo-log-04-01", -6, 3, 0, "猫粮 200g", ""),
    ("demo-log-04-02", -6, 0, 1, "猫粮 150g + 换清水", ""),
    ("demo-log-04-03", -6, 1, 2, "猫粮 200g", ""),
    ("demo-log-04-04", -6, 2, 0, "湿粮一罐", "花卷把罐头让给芝麻了。"),
    ("demo-log-05-01", -5, 0, 0, "猫粮 200g", ""),
    ("demo-log-05-02", -5, 1, 1, "猫粮 150g + 换清水", "清水盆洗过。"),
    ("demo-log-05-03", -5, 2, 2, "猫粮 200g", ""),
    ("demo-log-06-01", -4, 1, 0, "猫粮 200g", ""),
    ("demo-log-06-02", -4, 2, 1, "猫粮 150g", ""),
    ("demo-log-06-03", -4, 3, 2, "猫粮 180g + 换清水", ""),
    ("demo-log-06-04", -4, 0, 0, "猫粮 120g", "下雨，粮放在防潮盒里。"),
    ("demo-log-07-01", -3, 2, 0, "猫粮 200g", ""),
    ("demo-log-07-02", -3, 3, 1, "猫粮 150g + 换清水", ""),
    ("demo-log-07-03", -3, 0, 2, "猫粮 200g", ""),
    ("demo-log-08-01", -2, 3, 0, "猫粮 200g", ""),
    ("demo-log-08-02", -2, 0, 1, "猫粮 150g", "雪球在，没敢靠近。"),
    ("demo-log-08-03", -2, 1, 2, "猫粮 200g + 换清水", ""),
    ("demo-log-08-04", -2, 2, 0, "湿粮一罐", ""),
    ("demo-log-09-01", -1, 0, 0, "猫粮 200g", ""),
    ("demo-log-09-02", -1, 1, 1, "猫粮 180g", ""),
    ("demo-log-09-03", -1, 2, 2, "猫粮 150g + 换清水", ""),
    ("demo-log-10-01", 0, 1, 0, "猫粮 200g", ""),
    ("demo-log-10-02", 0, 2, 1, "猫粮 150g", ""),
    ("demo-log-10-03", 0, 3, 2, "猫粮 200g + 换清水", "沿河风大，碗压了石头。"),
    ("demo-log-10-04", 0, 0, 0, "猫粮 200g", ""),
)

# (id, cat_offset, day_offset_from_today, kind, title, detail)
DEMO_EVENTS: Tuple[Tuple[str, int, int, str, str, str], ...] = (
    ("demo-event-01-01", 0, -9, "RESCUE", "在 3 幢绿化带被发现", "雨天躲在配电箱后面，志愿者用航空箱带回。"),
    ("demo-event-01-02", 0, -5, "MEDICAL", "完成绝育手术", "在银湖宠物医院完成绝育，术后恢复良好。"),
    ("demo-event-01-03", 0, -2, "FEED", "回到北门投喂点", "熟悉环境后回到 3 幢绿化带，每天有人投喂。"),
    ("demo-event-02-01", 1, -7, "RESCUE", "从快递柜后救出", "被卡在快递柜和墙壁的缝隙里，志愿者合力救出。"),
    ("demo-event-02-02", 1, -3, "CHECKUP", "体检与驱虫", "体重 4.2kg，完成体内外驱虫。"),
    ("demo-event-03-01", 2, -6, "FEED", "开始定点投喂", "中心花园长椅下固定放粮，橘座每天都来。"),
    ("demo-event-03-02", 2, -1, "ADOPTED", "被 2 幢住户领养", "已进入家庭，志愿者定期回访。"),
    ("demo-event-04-01", 3, -8, "RESCUE", "地库入口首次记录", "夜间巡护时在地库入口拍到，胆子很小。"),
    ("demo-event-04-02", 3, -4, "NOTE", "确认健康状况良好", "连续投喂一周，精神食欲正常。"),
    ("demo-event-04-03", 3, -1, "CHECKUP", "安排免疫接种", "已完成第一针疫苗，两周后补第二针。"),
    ("demo-event-05-01", 4, -5, "MEDICAL", "右前爪旧伤换药", "旧伤有轻微感染，连续三天上药后结痂。"),
    ("demo-event-05-02", 4, -2, "NOTE", "恢复情况记录", "走路不再明显跛行，继续观察一周。"),
)

# (id, kind, amount, note, day_offset_from_today, cat_offset or None)
DEMO_IMPACTS: Tuple[Tuple[str, str, int, str, int, Optional[int]], ...] = (
    ("demo-impact-01", "RESCUED", 1, "雨夜从配电箱后救出奶牛", -9, 0),
    ("demo-impact-02", "RESCUED", 1, "从快递柜缝隙救出三花", -7, 1),
    ("demo-impact-03", "ADOPTED", 1, "橘座被 2 幢住户领养", -1, 2),
    ("demo-impact-04", "MEDICAL", 1, "奶牛绝育手术", -5, 0),
    ("demo-impact-05", "MEDICAL", 1, "花卷前爪换药治疗", -5, 4),
    ("demo-impact-06", "SUPPORTER", 1, "收到社区居民捐赠猫粮 20kg", -3, None),
)

# (id, day_offset_from_today, point_offset, user_offset) — a few slots stay free.
DEMO_SHIFTS: Tuple[Tuple[str, int, int, int], ...] = (
    ("demo-shift-01-01", 0, 0, 0),
    ("demo-shift-01-02", 0, 1, 1),
    ("demo-shift-02-01", 1, 1, 0),
    ("demo-shift-02-02", 1, 2, 2),
    ("demo-shift-03-01", 2, 3, 1),
    ("demo-shift-04-01", 3, 0, 2),
)

# table -> create order for the summary and for the cleanup preview.
SEED_TABLE_ORDER: Tuple[str, ...] = (
    "users",
    "communities",
    "cats",
    "feeding_points",
    "feeding_logs",
    "cat_events",
    "impact_events",
    "feeding_shifts",
)

# Delete children before parents; ids are only ever matched by the demo- prefix.
# Each table appears once, mirroring the per-table preview the CLI prints.
CLEANUP_ORDER: Tuple[Tuple[str, str], ...] = (
    ("feeding_logs", "id"),
    ("feeding_shifts", "id"),
    ("cat_events", "cat_id"),
    ("impact_events", "id"),
    ("feeding_points", "id"),
    ("cats", "id"),
    ("audit_logs", "entity_id"),
    ("communities", "id"),
    ("users", "id"),
)

# Extra sweeps run only on --execute, after the per-table preview above: a demo
# row carrying a non-demo id (hand-edited) still disappears rather than blocking
# the parent delete.
CLEANUP_SWEEPS: Tuple[Tuple[str, str], ...] = (("cat_events", "id"), ("audit_logs", "id"))

# Audit rows are written with the same shape the API's audit() helper produces.
DEMO_AUDIT_ACTION = "CREATE"

SEED_ENTITY_TYPES = {
    "users": "user",
    "communities": "community",
    "cats": "cat",
    "feeding_points": "feeding_point",
    "feeding_logs": "feeding_log",
    "cat_events": "cat_event",
    "impact_events": "impact_event",
    "feeding_shifts": "feeding_shift",
}


@dataclass
class SeedContext:
    """Resolved ids and a per-table created/skipped tally for one run."""

    session: Any
    now: datetime
    community_ids: List[str]
    counts: Dict[str, List[int]]

    def record(self, table: str, created: bool) -> None:
        tally = self.counts.setdefault(table, [0, 0])
        tally[0 if created else 1] += 1


def utc_now_naive() -> datetime:
    """Naive-UTC 'now', matching how the app's DateTime columns round-trip on SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(at: datetime) -> datetime:
    """Drop tzinfo, as SQLite stores these columns as naive UTC."""
    return at.astimezone(timezone.utc).replace(tzinfo=None)


def shanghai_today() -> Any:
    return datetime.now(CHINA_TZ).date()


def shanghai_datetime(day_offset: int, at: time) -> datetime:
    """A Shanghai wall-clock date+time expressed as naive UTC for storage."""
    day = shanghai_today() + timedelta(days=day_offset)
    return digest(datetime.combine(day, at, tzinfo=CHINA_TZ))


def shanghai_checkin_time(day_offset: int, at: time) -> datetime:
    """A check-in timestamp that is never in the future.

    Past days keep their scheduled wall-clock slot; today's slot is pulled back
    to at most 15 minutes ago, because a check-in cannot have happened later
    than now (otherwise 今日打卡 would look empty while fed_at points forward).
    """
    scheduled = shanghai_datetime(day_offset, at)
    if day_offset < 0:
        return scheduled
    latest = digest(datetime.now(timezone.utc) - timedelta(minutes=15))
    return min(scheduled, latest)


def _table_rows(session, table_name, id_column, id_value):
    table = models.Base.metadata.tables[table_name]
    column = table.c[id_column]
    return session.execute(select(func.count()).select_from(table).where(column == id_value)).scalar() or 0


def row_exists(session, table_name: str, id_value: str) -> bool:
    return bool(_table_rows(session, table_name, "id", id_value))


def prefix_count(session, table_name: str, column_name: str = "id") -> int:
    table = models.Base.metadata.tables[table_name]
    column = table.c[column_name]
    return session.execute(
        select(func.count()).select_from(table).where(column.like(DEMO_PREFIX + "%"))
    ).scalar() or 0


def insert_row(session, table_name: str, values: Dict[str, Any], id_value: str, context: SeedContext) -> bool:
    """Insert one demo row; return True when created, False when it already existed."""
    if row_exists(session, table_name, id_value):
        context.record(table_name, created=False)
        return False
    session.execute(insert(models.Base.metadata.tables[table_name]).values(**values))
    context.record(table_name, created=True)
    return True


def demo_audit(context: SeedContext, table_name: str, entity_id: str, after: Optional[Dict[str, Any]] = None) -> None:
    """Write one ``CREATE`` audit row in the shape the API's audit() helper uses.

    Deterministically idempotent: at most one row per (action, entity_id), so a
    re-run adds nothing. Cleanup matches these rows by the demo entity_id.
    """
    # Flush first so a duplicate entity id inside this same run is visible to the
    # count below (the session has autoflush disabled).
    context.session.flush()
    already = context.session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == DEMO_AUDIT_ACTION,
            AuditLog.entity_id == entity_id,
        )
    ).scalar() or 0
    if already:
        return
    context.session.add(AuditLog(
        actor_id=USER_IDS[0],
        action=DEMO_AUDIT_ACTION,
        entity_type=SEED_ENTITY_TYPES[table_name],
        entity_id=entity_id,
        before_json="{}",
        after_json=_json(after or {}),
    ))


def _json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def resolve_community_ids(session, context: SeedContext) -> List[str]:
    """Reuse ACTIVE non-QA communities when the database has them, else create ours."""
    existing = session.execute(
        select(Community.id)
        .where(
            Community.status == "ACTIVE",
            Community.is_qa.is_(False),
            Community.id.not_like(DEMO_PREFIX + "%"),
        )
        .order_by(Community.created_at.desc(), Community.id.desc())
        .limit(3)
    ).scalars().all()
    if existing:
        return list(existing)
    created_ids = []
    for community_id, name, street in DEMO_COMMUNITIES:
        created_ids.append(community_id)
        insert_row(session, "communities", {
            "id": community_id,
            "city": DEFAULT_CITY,
            "district": DEFAULT_DISTRICT,
            "street": street,
            "name": name,
            "normalized_name": normalize_community_name(name),
            "status": "ACTIVE",
            "review_note": "",
            "merged_into_id": None,
            "version": 1,
            "is_qa": False,
            "created_by": USER_IDS[0],
            "reviewed_by": None,
            "created_at": context.now,
            "updated_at": context.now,
        }, community_id, context)
        demo_audit(context, "communities", community_id, {"name": name, "status": "ACTIVE"})
    return created_ids


def seed_users(context: SeedContext) -> None:
    for user_id, nickname in DEMO_USERS:
        insert_row(context.session, "users", {
            "id": user_id,
            "openid": DEMO_OPENIDS[user_id],
            "username": DEMO_USERNAMES[user_id],
            "password_hash": None,
            "role": "USER",
            "status": "ACTIVE",
            "nickname": nickname,
            "created_at": context.now - timedelta(days=45),
            "last_login_at": context.now,
        }, user_id, context)


def seed_cats(context: SeedContext) -> None:
    for index, (cat_id, nickname, community_offset, location_note, health, living, note) in enumerate(DEMO_CATS):
        insert_row(context.session, "cats", {
            "id": cat_id,
            "community_id": context.community_ids[community_offset % len(context.community_ids)],
            "code": "DEMO-CAT-%02d" % (index + 1),
            "nickname": nickname,
            "living_status": living,
            "health_status": health,
            # The schema has no separate notes column, so the short Chinese
            # character note rides along in location_note (String(240)).
            "location_note": "%s｜%s" % (location_note, note),
            "latitude": None,
            "longitude": None,
            "photo_asset_id": None,
            "review_status": "APPROVED",
            "visibility_status": "ACTIVE",
            "created_by": USER_IDS[index % len(USER_IDS)],
            "idempotency_key": None,
            "profile_key": cat_id,
            "is_qa": False,
            "version": 1,
            "created_at": context.now - timedelta(days=30 - index),
            "updated_at": context.now,
        }, cat_id, context)
        demo_audit(context, "cats", cat_id, {"nickname": nickname, "review_status": "APPROVED"})


def seed_feeding_points(context: SeedContext) -> None:
    for point_id, name, community_offset, location_note, feeding_time, caretaker_note, latitude, longitude in DEMO_POINTS:
        insert_row(context.session, "feeding_points", {
            "id": point_id,
            "community_id": context.community_ids[community_offset % len(context.community_ids)],
            "name": name,
            "location_note": location_note,
            "feeding_time": feeding_time,
            "caretaker_note": caretaker_note,
            "latitude": latitude,
            "longitude": longitude,
            "status": "ACTIVE",
            "created_by": USER_IDS[0],
            "is_qa": False,
            "created_at": context.now - timedelta(days=21),
            "updated_at": context.now,
        }, point_id, context)
        demo_audit(context, "feeding_points", point_id, {"name": name})


def seed_feeding_logs(context: SeedContext) -> None:
    for log_id, day_offset, point_offset, user_offset, food_note, note in DEMO_LOGS:
        point_id = DEMO_POINTS[point_offset][0]
        user_id = USER_IDS[user_offset]
        slot = time(7, 30) if point_offset % 2 == 0 else time(18, 0)
        fed_at = shanghai_checkin_time(day_offset, slot)
        insert_row(context.session, "feeding_logs", {
            "id": log_id,
            "point_id": point_id,
            "user_id": user_id,
            "fed_on": (shanghai_today() + timedelta(days=day_offset)).isoformat(),
            "fed_at": fed_at,
            "food_note": food_note,
            "note": note,
            "photo_asset_id": None,
            "is_qa": False,
            "created_at": fed_at,
        }, log_id, context)


def seed_cat_events(context: SeedContext) -> None:
    for event_id, cat_offset, day_offset, kind, title, detail in DEMO_EVENTS:
        cat_id = DEMO_CATS[cat_offset][0]
        occurred_at = shanghai_datetime(day_offset, time(16, 0))
        insert_row(context.session, "cat_events", {
            "id": event_id,
            "cat_id": cat_id,
            "kind": kind,
            "title": title,
            "detail": detail,
            "occurred_at": occurred_at,
            "created_by": USER_IDS[cat_offset % len(USER_IDS)],
            "is_qa": False,
            "created_at": occurred_at,
        }, event_id, context)
        demo_audit(context, "cat_events", event_id, {"cat_id": cat_id, "kind": kind})


def seed_impact_events(context: SeedContext) -> None:
    for event_id, kind, amount, note, day_offset, cat_offset in DEMO_IMPACTS:
        occurred_at = shanghai_datetime(day_offset, time(10, 0))
        insert_row(context.session, "impact_events", {
            "id": event_id,
            "kind": kind,
            "amount": amount,
            "note": note,
            "occurred_at": occurred_at,
            "created_at": occurred_at,
            "created_by": USER_IDS[0],
            "reversed_at": None,
            "reversed_by": None,
            "is_qa": False,
        }, event_id, context)
        after = {"kind": kind, "amount": amount, "occurred_at": occurred_at.isoformat()}
        if cat_offset is not None:
            after["cat_id"] = DEMO_CATS[cat_offset][0]
        demo_audit(context, "impact_events", event_id, after)


def seed_feeding_shifts(context: SeedContext) -> None:
    for shift_id, day_offset, point_offset, user_offset in DEMO_SHIFTS:
        insert_row(context.session, "feeding_shifts", {
            "id": shift_id,
            "point_id": DEMO_POINTS[point_offset][0],
            "user_id": USER_IDS[user_offset],
            "shift_date": (shanghai_today() + timedelta(days=day_offset)).isoformat(),
            "status": "CLAIMED",
            "note": "" if day_offset else "今天我来。",
            "is_qa": False,
            "created_at": context.now,
            "updated_at": context.now,
        }, shift_id, context)
        demo_audit(context, "feeding_shifts", shift_id, {
            "point_id": DEMO_POINTS[point_offset][0],
            "shift_date": (shanghai_today() + timedelta(days=day_offset)).isoformat(),
            "status": "CLAIMED",
        })


def seed_demo_data(database_url: str) -> Dict[str, Any]:
    engine, session_factory = make_session_factory(database_url)
    ensure_schema(engine)
    with session_factory() as session:
        context = SeedContext(
            session=session,
            now=utc_now_naive(),
            community_ids=[],
            counts={},
        )
        seed_users(context)
        context.community_ids = resolve_community_ids(session, context)
        seed_cats(context)
        seed_feeding_points(context)
        seed_feeding_logs(context)
        seed_cat_events(context)
        seed_impact_events(context)
        seed_feeding_shifts(context)
        session.commit()
        visible = visible_cat_count(session)
        return {
            "counts": {table: context.counts.get(table, [0, 0]) for table in SEED_TABLE_ORDER},
            "community_ids": list(context.community_ids),
            "visible_cats": visible,
        }


def visible_cat_count(session) -> int:
    """Public pages show APPROVED + ACTIVE + is_qa=0; confirm the demo cats qualify."""
    return session.execute(
        select(func.count()).select_from(Cat).where(
            Cat.id.like(DEMO_PREFIX + "%"),
            Cat.is_qa.is_(False),
            Cat.review_status == "APPROVED",
            Cat.visibility_status == "ACTIVE",
        )
    ).scalar() or 0


def build_cleanup_preview(session) -> Dict[str, int]:
    preview: Dict[str, int] = {}
    for table_name, column_name in CLEANUP_ORDER:
        preview["%s.%s" % (table_name, column_name)] = prefix_count(session, table_name, column_name)
    return preview


def cleanup_demo_data(session, execute: bool = False) -> Dict[str, int]:
    preview = build_cleanup_preview(session)
    if not execute:
        return preview
    table_defs = models.Base.metadata.tables
    for table_name, column_name in CLEANUP_ORDER + CLEANUP_SWEEPS:
        table = table_defs[table_name]
        column = table.c[column_name]
        session.execute(table.delete().where(column.like(DEMO_PREFIX + "%")))
    session.commit()
    return preview


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--database-url",
        default=os.environ.get(DEFAULT_DATABASE_ENV),
        help="SQLAlchemy URL of the target database (default: $%s)" % DEFAULT_DATABASE_ENV,
    )
    parser.add_argument("--cleanup", action="store_true", help="preview (and with --execute, remove) the demo rows")
    parser.add_argument("--execute", action="store_true", help="actually delete during --cleanup; without it nothing is removed")
    arguments = parser.parse_args(argv)
    if not arguments.database_url:
        parser.error("--database-url is required (or set %s)" % DEFAULT_DATABASE_ENV)
    if arguments.execute and not arguments.cleanup:
        parser.error("--execute only applies to --cleanup")
    return arguments


def print_summary(rows: Sequence[Tuple[str, int, int]]) -> None:
    width = max(len(name) for name, _, _ in rows) if rows else 5
    width = max(width, len("table"))
    print("%-*s | %8s | %8s" % (width, "table", "created", "skipped"))
    print("%s-+-%s-+-%s" % ("-" * width, "-" * 8, "-" * 8))
    for name, created, skipped in rows:
        print("%-*s | %8d | %8d" % (width, name, created, skipped))
    total_created = sum(created for _, created, _ in rows)
    total_skipped = sum(skipped for _, _, skipped in rows)
    print("%-*s | %8d | %8d" % (width, "TOTAL", total_created, total_skipped))


def print_result_line(mode: str) -> None:
    if mode == "cleanup-execute":
        print("executed: deletion was committed")
    elif mode == "cleanup-preview":
        print("dry run: no rows were deleted")
    else:
        print("seed run is idempotent: existing demo- ids were skipped, nothing was deleted")


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_args(argv)
    engine, session_factory = make_session_factory(arguments.database_url)
    context_note = "database: %s" % arguments.database_url
    if arguments.cleanup:
        with session_factory() as session:
            preview = cleanup_demo_data(session, execute=arguments.execute)
        print(context_note)
        print("%-24s | %8s" % ("table.column", "to_delete"))
        print("%s-+-%s" % ("-" * 24, "-" * 8))
        for key, count in preview.items():
            print("%-24s | %8d" % (key, count))
        print("%-24s | %8d" % ("TOTAL", sum(preview.values())))
        print_result_line("cleanup-execute" if arguments.execute else "cleanup-preview")
        return 0

    result = seed_demo_data(arguments.database_url)
    print(context_note)
    rows = [(table, result["counts"][table][0], result["counts"][table][1]) for table in SEED_TABLE_ORDER]
    print_summary(rows)
    print("publicly visible demo cats (is_qa=0, APPROVED, ACTIVE): %d" % result["visible_cats"])
    print("community ids used: %s" % ", ".join(result["community_ids"]))
    print_result_line("seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
