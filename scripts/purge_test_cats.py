#!/usr/bin/env python3
"""一次性数据修复：清掉测试残留的猫咪档案，并把有猫照片的档案移出已归档小区。

为什么要有这个脚本而不是敲一条 SQL：这几个 id 是**逐个看过照片**之后才决定删的，
理由必须和 id 写在一起、可复查、可重跑。2026-09-24 的照片审计结果：

    大黑B  b92ee3da  头像不是猫：阿据船舶备件后台（AJV 供应商页面）截图
    小黑   e14422dd  头像不是猫：夜晚马路的照片
    QA×6  [QA-20260801] ...  2026-08-01 那批 QA fixture（其中"管理员录入白猫"的
                             照片是个 19 字节的坏 jpeg）
    三花   c690d3a0  照片是真猫，但它挂在已归档的 QA 小区下，公开页永远看不到

删除是不可逆的，所以这里和其他脚本一样：默认只预览，`--execute` 才落库，
删之前先确认媒体文件在备份里（`scripts/backup_offsite.sh` 的快照包含 uploads.tar.gz）。

    python scripts/purge_test_cats.py --database-url sqlite:////opt/help-cat/data/help-cat.db \
        --storage-root /opt/help-cat/data/uploads
    python scripts/purge_test_cats.py ... --execute
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))

from sqlalchemy import delete, func, select, update  # noqa: E402

from helpcat import models  # noqa: E402,F401 - registers every table on Base.metadata
from helpcat.db import make_session_factory  # noqa: E402
from helpcat.media import media_thumbnail_path  # noqa: E402
from helpcat.models import AuditLog, Cat, CatEvent, Community, MediaAsset, User  # noqa: E402

DEFAULT_DATABASE_ENV = "HELPCAT_DATABASE_URL"

# (cat_id, 为什么删)
PURGE: Tuple[Tuple[str, str], ...] = (
    ("b92ee3daf3d24c6cb982ac11954daae1", "头像不是猫：阿据船舶备件后台截图"),
    ("e14422dd", "头像不是猫：夜晚马路照片"),
    ("62e8f758", "QA fixture：2026-08-01 待审核橘猫"),
    ("f17aa012", "QA fixture：2026-08-01 已公开奶牛猫"),
    ("1b7bf818", "QA fixture：2026-08-01 未通过狸花猫"),
    ("1cc86321", "QA fixture：2026-08-01 已隐藏三花猫"),
    ("bf997254", "QA fixture：2026-08-01 已归档黑猫"),
    ("28fb0f77", "QA fixture：2026-08-01 管理员录入白猫（照片是 19 字节坏文件）"),
)

# (cat_id, 目标小区名, 为什么移)
REASSIGN: Tuple[Tuple[str, str, str], ...] = (
    ("c690d3a0", "银湖街道", "照片是真猫，但原小区是已归档的 QA 小区，公开页看不到"),
)


def utc_now():
    return datetime.now(timezone.utc)


def match_cat(session, prefix: str) -> Optional[Cat]:
    """允许写短前缀，但必须唯一命中，避免误删同前缀的另一只。"""
    rows = session.scalars(select(Cat).where(Cat.id.like(prefix + "%"))).all()
    if len(rows) > 1:
        raise SystemExit("前缀 %s 命中 %d 条，写全一点" % (prefix, len(rows)))
    return rows[0] if rows else None


def actor_id(session) -> Optional[str]:
    for role in ("SUPER_ADMIN", "ADMIN"):
        user = session.scalar(select(User).where(User.role == role).order_by(User.created_at))
        if user:
            return user.id
    user = session.scalar(select(User).order_by(User.created_at))
    return user.id if user else None


def collect(session) -> Dict[str, object]:
    purge, missing = [], []
    for prefix, reason in PURGE:
        cat = match_cat(session, prefix)
        if cat is None:
            missing.append(prefix)
        else:
            purge.append((cat, reason))
    reassign = []
    for prefix, community_name, reason in REASSIGN:
        cat = match_cat(session, prefix)
        if cat is None:
            missing.append(prefix)
            continue
        community = session.scalar(select(Community).where(Community.name == community_name))
        if community is None:
            raise SystemExit("找不到小区：%s" % community_name)
        reassign.append((cat, community, reason))

    media_ids = [cat.photo_asset_id for cat, _ in purge if cat.photo_asset_id]
    media = session.scalars(select(MediaAsset).where(MediaAsset.id.in_(media_ids))).all() if media_ids else []
    return {"purge": purge, "reassign": reassign, "media": list(media), "missing": missing}


def describe(plan: Dict[str, object]) -> None:
    print("=== 将移动的小区归属 ===")
    for cat, community, reason in plan["reassign"]:
        print("  %-8s %-8s -> %-8s  %s" % (cat.id[:8], cat.community.name if cat.community else "?", community.name, reason))
    print("=== 将删除的档案 ===")
    for cat, reason in plan["purge"]:
        photo = "有照片" if cat.photo_asset_id else "无照片"
        print("  %-8s %-18s %-14s %-8s %s" % (cat.id[:8], cat.nickname, cat.review_status, photo, reason))
    print("=== 随之删除的媒体 ===")
    for asset in plan["media"]:
        print("  %s  %s  %s  %d bytes" % (asset.id[:8], asset.object_key, asset.content_type, asset.byte_size))
    if plan["missing"]:
        print("· 库里已经没有（跳过）：%s" % ", ".join(plan["missing"]))


def run(database_url: str, storage_root: Path, execute: bool) -> Dict[str, object]:
    engine, session_factory = make_session_factory(database_url)
    with session_factory() as session:
        plan = collect(session)
        describe(plan)
        if not execute:
            print("\n这是预览。确认无误后加 --execute。")
            return {"reassigned": 0, "deleted_cats": 0, "deleted_media": 0, "executed": False}

        actor = actor_id(session)
        now = utc_now()

        reassigned = 0
        for cat, community, reason in plan["reassign"]:
            if cat.community_id == community.id:
                # 已经在目标小区：重跑不该再升版本、再写一条审计。
                continue
            before = {"community_id": cat.community_id}
            session.execute(
                update(Cat)
                .where(Cat.id == cat.id)
                .values(community_id=community.id, version=func.coalesce(Cat.version, 1) + 1, updated_at=now)
            )
            session.add(AuditLog(
                actor_id=actor, action="REASSIGN", entity_type="cat", entity_id=cat.id,
                before_json=json.dumps(before, ensure_ascii=False),
                after_json=json.dumps({"community_id": community.id, "reason": reason}, ensure_ascii=False),
                created_at=now,
            ))
            reassigned += 1

        removed_files = 0
        for asset in plan["media"]:
            for path in (storage_root / asset.object_key, media_thumbnail_path(storage_root, asset.object_key)):
                if path.exists():
                    path.unlink()
                    removed_files += 1

        purged_ids = [cat.id for cat, _ in plan["purge"]]
        deleted_events = 0
        if purged_ids:
            deleted_events = session.execute(
                delete(CatEvent).where(CatEvent.cat_id.in_(purged_ids))
            ).rowcount or 0
            session.add(AuditLog(
                actor_id=actor, action="PURGE", entity_type="cat", entity_id=",".join(sorted(purged_ids)),
                before_json=json.dumps(
                    {cat.id: {"nickname": cat.nickname, "reason": reason} for cat, reason in plan["purge"]},
                    ensure_ascii=False),
                after_json="{}", created_at=now,
            ))
            session.execute(delete(Cat).where(Cat.id.in_(purged_ids)))
        if plan["media"]:
            session.execute(delete(MediaAsset).where(MediaAsset.id.in_([asset.id for asset in plan["media"]])))
        session.commit()

        return {
            "reassigned": reassigned,
            "deleted_cats": len(purged_ids),
            "deleted_media": len(plan["media"]),
            "deleted_files": removed_files,
            "deleted_cat_events": deleted_events,
            "executed": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.getenv(DEFAULT_DATABASE_ENV, ""))
    parser.add_argument("--storage-root", default=os.getenv("HELPCAT_STORAGE_ROOT", ""))
    parser.add_argument("--execute", action="store_true", help="真的落库（默认只预览）")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("需要 --database-url 或 HELPCAT_DATABASE_URL")
    if not args.storage_root:
        parser.error("需要 --storage-root 或 HELPCAT_STORAGE_ROOT")
    print(run(args.database_url, Path(args.storage_root), args.execute))
    return 0


if __name__ == "__main__":
    sys.exit(main())
