#!/usr/bin/env python3
"""Preview or remove one exact Help Cat QA batch from its manifest."""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    from scripts.help_cat_qa_seed import BATCH, validate_manifest
except ModuleNotFoundError:
    from help_cat_qa_seed import BATCH, validate_manifest


def _ids(manifest, section):
    return [item["id"] for item in manifest[section].values()]


def _count_ids(connection, table, column, values):
    if not values:
        return 0
    placeholders = ",".join("?" for _ in values)
    return connection.execute("SELECT COUNT(*) FROM %s WHERE %s IN (%s)" % (table, column, placeholders), values).fetchone()[0]


def _media_target(storage_root, object_key):
    root = Path(storage_root).resolve()
    target = (root / object_key).resolve()
    if target.parent != root:
        raise ValueError("manifest media object_key escapes storage root")
    return target


def build_cleanup_preview(connection, storage_root, manifest):
    validate_manifest(manifest)
    user_ids = _ids(manifest, "users")
    community_ids = _ids(manifest, "communities")
    cat_ids = _ids(manifest, "cats")
    task_ids = _ids(manifest, "tasks")
    media_ids = [manifest["media"]["id"]]
    entity_ids = user_ids + community_ids + cat_ids + task_ids + media_ids
    entity_placeholders = ",".join("?" for _ in entity_ids)
    actor_placeholders = ",".join("?" for _ in user_ids)
    audit_count = connection.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE entity_id IN (%s) OR actor_id IN (%s)" % (entity_placeholders, actor_placeholders),
        entity_ids + user_ids,
    ).fetchone()[0]
    media_files = 0
    if _media_target(storage_root, manifest["media"]["object_key"]).is_file():
        media_files = 1
    return {
        "audit_logs": audit_count,
        "sessions": _count_ids(connection, "sessions", "user_id", user_ids),
        "daily_cat_quotas": _count_ids(connection, "daily_cat_quotas", "user_id", user_ids),
        "tasks": _count_ids(connection, "tasks", "id", task_ids),
        "cats": _count_ids(connection, "cats", "id", cat_ids),
        "media_assets": _count_ids(connection, "media_assets", "id", media_ids),
        "communities": _count_ids(connection, "communities", "id", community_ids),
        "users": _count_ids(connection, "users", "id", user_ids),
        "media_files": media_files,
    }


def _delete_ids(connection, table, column, values):
    if not values:
        return
    placeholders = ",".join("?" for _ in values)
    connection.execute("DELETE FROM %s WHERE %s IN (%s)" % (table, column, placeholders), values)


def cleanup(connection, storage_root, manifest, execute=False):
    validate_manifest(manifest)
    preview = build_cleanup_preview(connection, storage_root, manifest)
    if not execute:
        return preview

    user_ids = _ids(manifest, "users")
    community_ids = _ids(manifest, "communities")
    cat_ids = _ids(manifest, "cats")
    task_ids = _ids(manifest, "tasks")
    media_ids = [manifest["media"]["id"]]
    entity_ids = user_ids + community_ids + cat_ids + task_ids + media_ids
    entity_placeholders = ",".join("?" for _ in entity_ids)
    actor_placeholders = ",".join("?" for _ in user_ids)
    connection.execute(
        "DELETE FROM audit_logs WHERE entity_id IN (%s) OR actor_id IN (%s)" % (entity_placeholders, actor_placeholders),
        entity_ids + user_ids,
    )
    _delete_ids(connection, "sessions", "user_id", user_ids)
    _delete_ids(connection, "daily_cat_quotas", "user_id", user_ids)
    _delete_ids(connection, "tasks", "id", task_ids)
    _delete_ids(connection, "cats", "id", cat_ids)
    _delete_ids(connection, "media_assets", "id", media_ids)
    _delete_ids(connection, "communities", "id", community_ids)
    _delete_ids(connection, "users", "id", user_ids)
    connection.commit()

    target = _media_target(storage_root, manifest["media"]["object_key"])
    if target.is_file():
        target.unlink()
    return preview


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, default=Path("/opt/help-cat/backups"))
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args(argv)

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    backup = None
    if arguments.execute:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = arguments.backup_root / (stamp + "-before-cleanup-" + BATCH)
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup = backup_dir / arguments.database.name
        shutil.copy2(str(arguments.database), str(backup))
    with sqlite3.connect(str(arguments.database)) as connection:
        result = cleanup(connection, arguments.storage_root, manifest, execute=arguments.execute)
    print(json.dumps({"status": "deleted" if arguments.execute else "dry-run", "batch": BATCH, "counts": result, "backup": str(backup) if backup else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
