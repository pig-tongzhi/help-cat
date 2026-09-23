#!/usr/bin/env python3
"""把「演示猫档案」（含照片）写进一个 help-cat 库，并且能整体收回。

和 `seed_demo_data.py` 一样属于**演示数据**，不是 QA 数据：`is_qa=0`、审核通过、
已发布，所以普通用户真的看得到。区别是这批带照片 —— 线上首页最缺的就是「有图、
名字正常」的档案。

照片来自 `scripts/showcase_photos/`（公有领域 / CC0，来源与许可见同目录
`SOURCES.md`）。这批照片是**占位**：等有真实救助照片时，先
`--cleanup --execute` 整体删掉，再按正常流程上传真实档案。

写入走的是和站内上传**同一条代码路径**（`sanitize_public_image` +
`create_media_thumbnail`），所以产出与真人上传完全同构：元数据被清掉、缩略图
是同一规格的 webp。

每一行都用固定主键 `showcase-` 前缀，可精确回收：

    showcase-cat-01  showcase-media-01

幂等：已存在的 id 只报告跳过，绝不改写。默认只预览，必须 `--execute` 才落库。

    python scripts/seed_showcase_cats.py --database-url sqlite:////opt/help-cat/data/help-cat.db \
        --storage-root /opt/help-cat/data/uploads
    python scripts/seed_showcase_cats.py --database-url ... --storage-root ... --execute
    python scripts/seed_showcase_cats.py --database-url ... --storage-root ... --cleanup --execute
"""

import argparse
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))

from sqlalchemy import delete, func, select  # noqa: E402

from helpcat import models  # noqa: E402,F401 - registers every table on Base.metadata
from helpcat.config import Settings  # noqa: E402
from helpcat.db import ensure_schema, make_session_factory  # noqa: E402
from helpcat.media import create_media_thumbnail, media_thumbnail_path, sanitize_public_image  # noqa: E402
from helpcat.models import AuditLog, Cat, Community, MediaAsset, User, new_id  # noqa: E402

PHOTO_DIR = SCRIPT_DIR / "showcase_photos"
CAT_PREFIX = "showcase-cat-"
MEDIA_PREFIX = "showcase-media-"
DEFAULT_DATABASE_ENV = "HELPCAT_DATABASE_URL"

# 名字都按照片里的花色起，不用「测试猫 A」这种一眼假的名字。
# community 用小区名匹配，找不到就退到第一个 ACTIVE 小区。
SHOWCASE_CATS: Tuple[Dict[str, str], ...] = (
    {
        "slot": "00", "nickname": "汤圆", "health_status": "HEALTHY", "living_status": "在小区里生活",
        "location_note": "长毛狸白，蓝眼睛，冬天毛会更蓬。傍晚常出现在花坛边。", "community": "银湖街道",
    },
    {
        "slot": "02", "nickname": "花卷", "health_status": "HEALTHY", "living_status": "在小区里生活",
        "location_note": "三花，喜欢蹲在排水口边看水，胆子不小，人靠得比较近也不跑。", "community": "上林南路",
    },
    {
        "slot": "04", "nickname": "灰灰", "health_status": "HEALTHY", "living_status": "有人定点照护",
        "location_note": "灰色狸花，脖子上有志愿者给戴的蓝色项圈，会在楼道口等饭。", "community": "缙云大厦",
    },
    {
        "slot": "08", "nickname": "年糕", "health_status": "HEALTHY", "living_status": "在小区里生活",
        "location_note": "长毛狸白，喜欢趴在草丛里，喊名字会抬头看你一眼。", "community": "银湖街道",
    },
    {
        "slot": "09", "nickname": "豆花", "health_status": "HEALTHY", "living_status": "在小区里生活",
        "location_note": "三花，爱蹲在矮墙上晒太阳，路过的人它基本都认识。", "community": "上林南路",
    },
    {
        "slot": "10", "nickname": "墨镜", "health_status": "HEALTHY", "living_status": "在小区里生活",
        "location_note": "黑白花色，一只眼睛周围正好一片黑，像戴了副墨镜。", "community": "缙云大厦",
    },
    {
        "slot": "11", "nickname": "虎子", "health_status": "NEEDS_HELP", "living_status": "志愿者持续观察",
        "location_note": "狸白，前爪有旧伤，走路略微跛，志愿者在持续观察并准备带去看医生。", "community": "上林南路",
    },
    {
        "slot": "14", "nickname": "大橘", "health_status": "HEALTHY", "living_status": "在小区里生活",
        "location_note": "橘猫，胃口很好，见人凑过来要吃的，是这个片区最胖的一只。", "community": "银湖街道",
    },
)


@dataclass
class Plan:
    create_cats: List[str]
    skip_cats: List[str]
    missing_photos: List[str]
    communities: Dict[str, str]
    admin_id: Optional[str]


def utc_now():
    return datetime.now(timezone.utc)


def resolve_admin(session) -> Optional[str]:
    """媒体与档案都要 created_by，挑一个真实存在的管理员（没有就挑任意用户）。"""
    for role in ("SUPER_ADMIN", "ADMIN"):
        user = session.scalar(select(User).where(User.role == role).order_by(User.created_at))
        if user:
            return user.id
    user = session.scalar(select(User).order_by(User.created_at))
    return user.id if user else None


def resolve_communities(session) -> Dict[str, str]:
    rows = session.scalars(select(Community).where(Community.status == "ACTIVE", Community.is_qa.is_(False))).all()
    return {row.name: row.id for row in rows}


def build_plan(session) -> Plan:
    communities = resolve_communities(session)
    create, skip, missing = [], [], []
    for item in SHOWCASE_CATS:
        cat_id = CAT_PREFIX + item["slot"]
        if session.get(Cat, cat_id):
            skip.append(cat_id)
        elif not (PHOTO_DIR / (item["slot"] + ".webp")).exists():
            missing.append(item["slot"] + ".webp")
        else:
            create.append(cat_id)
    return Plan(create, skip, missing, communities, resolve_admin(session))


def describe(plan: Plan) -> None:
    print("照片目录: %s" % PHOTO_DIR)
    print("小区: %s" % (", ".join(sorted(plan.communities)) or "（没有 ACTIVE 小区，会回退到第一个）"))
    print("将新建: %s" % (", ".join(plan.create_cats) or "（无）"))
    if plan.skip_cats:
        print("已存在跳过: %s" % ", ".join(plan.skip_cats))
    if plan.missing_photos:
        print("!! 缺照片: %s（先跑 scripts/fetch_showcase_photos.py --install）" % ", ".join(plan.missing_photos))
    if plan.admin_id is None:
        print("!! 库里一个用户都没有，无法确定 created_by")
    for item in SHOWCASE_CATS:
        if CAT_PREFIX + item["slot"] in plan.create_cats:
            print("  %s  %-4s %-10s %s" % (item["slot"], item["nickname"], item["health_status"], item["location_note"][:24]))


def seed(database_url: str, storage_root: Path) -> Dict[str, Any]:
    settings = Settings(database_url=database_url, storage_root=storage_root)
    engine, session_factory = make_session_factory(database_url)
    ensure_schema(engine)
    settings.storage_root.mkdir(parents=True, exist_ok=True)

    created, media_created = 0, 0
    with session_factory() as session:
        plan = build_plan(session)
        if plan.admin_id is None:
            raise SystemExit("库里没有用户，先注册一个管理员再跑这个脚本")
        fallback_community = next(iter(plan.communities.values()), None)

        for item in SHOWCASE_CATS:
            cat_id = CAT_PREFIX + item["slot"]
            media_id = MEDIA_PREFIX + item["slot"]
            if session.get(Cat, cat_id):
                continue
            source = PHOTO_DIR / (item["slot"] + ".webp")
            if not source.exists():
                continue
            sanitized, content_type, extension = sanitize_public_image(
                source.read_bytes(), "image/webp", settings.max_image_pixels, settings.max_image_bytes,
            )
            asset = MediaAsset(
                id=media_id, object_key=new_id() + extension, content_type=content_type,
                byte_size=len(sanitized), created_by=plan.admin_id, created_at=utc_now(),
            )
            target = settings.storage_root / asset.object_key
            target.write_bytes(sanitized)
            create_media_thumbnail(target, media_thumbnail_path(settings.storage_root, asset.object_key))
            session.add(asset)
            session.flush()
            media_created += 1

            cat = Cat(
                id=cat_id, community_id=plan.communities.get(item["community"], fallback_community),
                code="HC-" + secrets.token_hex(4).upper(), nickname=item["nickname"],
                living_status=item["living_status"], health_status=item["health_status"],
                location_note=item["location_note"], photo_asset_id=asset.id,
                review_status="APPROVED", visibility_status="ACTIVE", is_qa=False, version=1,
                created_by=plan.admin_id,
            )
            session.add(cat)
            session.flush()
            session.add(AuditLog(
                actor_id=plan.admin_id, action="SEED", entity_type="cat", entity_id=cat.id,
                before_json="{}", after_json='{"source": "showcase"}', created_at=utc_now(),
            ))
            created += 1
        session.commit()

        visible = session.scalar(
            select(func.count()).select_from(Cat).where(
                Cat.review_status == "APPROVED", Cat.visibility_status == "ACTIVE", Cat.is_qa.is_(False),
            )
        )
    return {"created": created, "media_created": media_created, "visible_cats": visible}


def cleanup(database_url: str, storage_root: Path, execute: bool) -> Dict[str, Any]:
    settings = Settings(database_url=database_url, storage_root=storage_root)
    engine, session_factory = make_session_factory(database_url)
    with session_factory() as session:
        cats = session.scalars(select(Cat).where(Cat.id.like(CAT_PREFIX + "%"))).all()
        assets = session.scalars(select(MediaAsset).where(MediaAsset.id.like(MEDIA_PREFIX + "%"))).all()
        print("将删除: cats=%d media_assets=%d（照片与缩略图文件一并删除）" % (len(cats), len(assets)))
        for cat in cats:
            print("  %s %s" % (cat.id, cat.nickname))
        if not execute:
            print("\n这是预览。确认无误后加 --execute。")
            return {"cats": len(cats), "media": len(assets), "executed": False}

        removed_files = 0
        for asset in assets:
            for path in (settings.storage_root / asset.object_key,
                         media_thumbnail_path(settings.storage_root, asset.object_key)):
                if path.exists():
                    path.unlink()
                    removed_files += 1
            session.execute(delete(AuditLog).where(AuditLog.entity_id == asset.id))
        for cat in cats:
            session.execute(delete(AuditLog).where(AuditLog.entity_id == cat.id))
        session.execute(delete(Cat).where(Cat.id.like(CAT_PREFIX + "%")))
        session.execute(delete(MediaAsset).where(MediaAsset.id.like(MEDIA_PREFIX + "%")))
        session.commit()
    return {"cats": len(cats), "media": len(assets), "files": removed_files, "executed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.getenv(DEFAULT_DATABASE_ENV, ""))
    parser.add_argument("--storage-root", default=os.getenv("HELPCAT_STORAGE_ROOT", ""))
    parser.add_argument("--execute", action="store_true", help="真的写库/删库（默认只预览）")
    parser.add_argument("--cleanup", action="store_true", help="改为回收全部 showcase- 数据")
    parser.add_argument("--list", action="store_true", help="只打印计划")
    args = parser.parse_args()

    if not args.database_url:
        parser.error("需要 --database-url 或 HELPCAT_DATABASE_URL")
    if not args.storage_root:
        parser.error("需要 --storage-root 或 HELPCAT_STORAGE_ROOT")
    storage_root = Path(args.storage_root)

    if args.cleanup:
        print(cleanup(args.database_url, storage_root, args.execute))
        return 0

    engine, session_factory = make_session_factory(args.database_url)
    ensure_schema(engine)
    with session_factory() as session:
        plan = build_plan(session)
    describe(plan)
    if args.list or not args.execute:
        if not args.list:
            print("\n这是预览。确认无误后加 --execute。")
        return 0
    print(seed(args.database_url, storage_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
