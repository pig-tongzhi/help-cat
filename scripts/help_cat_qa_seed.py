#!/usr/bin/env python3
"""Create the namespaced Help Cat production QA dataset through the HTTP API."""

import argparse
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

BATCH = "QA-20260801"
PREFIX = "[QA-20260801] "
REQUIRED_AUDIT_ACTIONS = {"ROLE_CHANGE", "CREATE", "UPLOAD", "REVIEW", "VISIBILITY", "ARCHIVE", "CLAIM"}


@dataclass(frozen=True)
class SeedConfig:
    base_url: str
    database: Path
    storage_root: Path
    manifest: Path
    credentials: Path


class ApiClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def json(self, method, path, payload=None, token=None, expected=200):
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        status, response = self._open(request)
        if status != expected:
            code = response.get("code") if isinstance(response, dict) else "invalid_response"
            raise RuntimeError("%s %s returned %s (%s)" % (method, path, status, code))
        return response

    def upload_jpeg(self, path, content, token, expected=201):
        boundary = "----HelpCatQa%s" % secrets.token_hex(12)
        body = (
            ("--%s\r\n" % boundary).encode()
            + b'Content-Disposition: form-data; name="file"; filename="qa-cat.jpg"\r\n'
            + b"Content-Type: image/jpeg\r\n\r\n"
            + content
            + ("\r\n--%s--\r\n" % boundary).encode()
        )
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Authorization": "Bearer " + token, "Content-Type": "multipart/form-data; boundary=" + boundary},
            method="POST",
        )
        status, response = self._open(request)
        if status != expected:
            code = response.get("code") if isinstance(response, dict) else "invalid_response"
            raise RuntimeError("POST %s returned %s (%s)" % (path, status, code))
        return response

    def bytes(self, path, expected=200):
        request = urllib.request.Request(self.base_url + path, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            body = error.read()
        if status != expected:
            raise RuntimeError("GET %s returned %s" % (path, status))
        return body

    @staticmethod
    def _open(request):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                content = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            content = error.read()
            status = error.code
        try:
            body = json.loads(content.decode("utf-8")) if content else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        return status, body


def qa_accounts():
    return {
        "admin": {"username": "qa_admin_20260801", "role": "ADMIN"},
        "user_a": {"username": "qa_user_a_20260801", "role": "USER"},
        "user_b": {"username": "qa_user_b_20260801", "role": "USER"},
    }


def expected_entities():
    return {
        "communities": {
            "active": {"name": PREFIX + "星河家园", "status": "ACTIVE"},
            "pending": {"name": PREFIX + "待审核小区", "status": "PENDING_REVIEW"},
            "hidden": {"name": PREFIX + "未通过小区", "status": "HIDDEN"},
            "archived": {"name": PREFIX + "已归档小区", "status": "ARCHIVED"},
        },
        "cats": {
            "pending": {"name": PREFIX + "待审核橘猫", "review_status": "PENDING_REVIEW", "visibility_status": "ACTIVE"},
            "public": {"name": PREFIX + "已公开奶牛猫", "review_status": "APPROVED", "visibility_status": "ACTIVE"},
            "rejected": {"name": PREFIX + "未通过狸花猫", "review_status": "REJECTED", "visibility_status": "ACTIVE"},
            "hidden": {"name": PREFIX + "已隐藏三花猫", "review_status": "APPROVED", "visibility_status": "HIDDEN"},
            "archived": {"name": PREFIX + "已归档黑猫", "review_status": "APPROVED", "visibility_status": "ARCHIVED"},
            "admin_photo": {"name": PREFIX + "管理员录入白猫", "review_status": "APPROVED", "visibility_status": "ACTIVE"},
        },
        "tasks": {
            "open": {"name": PREFIX + "小区晚间补粮", "status": "OPEN"},
            "claimed": {"name": PREFIX + "东门猫窝巡查", "status": "CLAIMED"},
        },
    }


def _require_entity_ids(manifest, section, expected):
    actual = manifest.get(section)
    if not isinstance(actual, dict) or set(actual) != set(expected):
        raise ValueError("manifest %s entries do not match expected batch" % section)
    for key, expected_value in expected.items():
        item = actual[key]
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError("manifest %s.%s id is required" % (section, key))
        for field in expected_value:
            if item.get(field) != expected_value[field]:
                raise ValueError("manifest %s.%s %s mismatch" % (section, key, field))


def validate_manifest(manifest):
    if manifest.get("batch") != BATCH or manifest.get("prefix") != PREFIX:
        raise ValueError("manifest batch namespace mismatch")
    users = manifest.get("users")
    expected_users = qa_accounts()
    if not isinstance(users, dict) or set(users) != set(expected_users):
        raise ValueError("manifest user entries do not match expected batch")
    for key, expected in expected_users.items():
        user = users[key]
        if not user.get("id"):
            raise ValueError("manifest users.%s id is required" % key)
        if user.get("username") != expected["username"] or user.get("role") != expected["role"]:
            raise ValueError("manifest users.%s mismatch" % key)

    entities = expected_entities()
    _require_entity_ids(manifest, "communities", entities["communities"])
    _require_entity_ids(manifest, "cats", entities["cats"])
    _require_entity_ids(manifest, "tasks", entities["tasks"])

    media = manifest.get("media") or {}
    if not media.get("id") or not media.get("object_key"):
        raise ValueError("manifest media id and object_key are required")
    if not REQUIRED_AUDIT_ACTIONS.issubset(set(manifest.get("audit_actions") or [])):
        raise ValueError("manifest audit actions are incomplete")
    super_admin = manifest.get("super_admin") or {}
    if super_admin != {"count": 1, "username": "zack", "role": "SUPER_ADMIN"}:
        raise ValueError("manifest super administrator invariant failed")
    return manifest


def _database_preflight(config):
    if config.manifest.exists():
        raise RuntimeError("manifest already exists: %s" % config.manifest)
    if config.credentials.exists():
        raise RuntimeError("credentials already exist: %s" % config.credentials)
    if not config.database.is_file():
        raise RuntimeError("database does not exist: %s" % config.database)
    with sqlite3.connect(str(config.database)) as connection:
        supers = connection.execute("SELECT username, role, status FROM users WHERE role = 'SUPER_ADMIN'").fetchall()
        if supers != [("zack", "SUPER_ADMIN", "ACTIVE")]:
            raise RuntimeError("zack must be the sole active SUPER_ADMIN")
        usernames = tuple(item["username"] for item in qa_accounts().values())
        placeholders = ",".join("?" for _ in usernames)
        if connection.execute("SELECT COUNT(*) FROM users WHERE username IN (%s)" % placeholders, usernames).fetchone()[0]:
            raise RuntimeError("QA usernames already exist")
        for table, column in (("communities", "name"), ("cats", "nickname"), ("tasks", "title")):
            if connection.execute("SELECT COUNT(*) FROM %s WHERE %s LIKE ?" % (table, column), (PREFIX + "%",)).fetchone()[0]:
                raise RuntimeError("QA entities already exist in %s" % table)


def _temporary_super_session(database):
    token = secrets.token_urlsafe(48)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None).isoformat(sep=" ")
    with sqlite3.connect(str(database)) as connection:
        row = connection.execute("SELECT id FROM users WHERE username = 'zack' AND role = 'SUPER_ADMIN' AND status = 'ACTIVE'").fetchall()
        if len(row) != 1:
            raise RuntimeError("cannot issue temporary zack session")
        connection.execute("INSERT INTO sessions(token, user_id, expires_at, revoked_at) VALUES (?, ?, ?, NULL)", (token, row[0][0], expires))
        connection.commit()
    return token


def _remove_session(database, token):
    if not token:
        return
    with sqlite3.connect(str(database)) as connection:
        connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        connection.commit()


def _atomic_private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%s" % secrets.token_hex(6))
    temporary.write_text(text, encoding="utf-8")
    os.chmod(str(temporary), 0o600)
    os.replace(str(temporary), str(path))


def _rollback_partial(config, created):
    user_ids = list(created.get("user_ids", []))
    entity_ids = list(created.get("entity_ids", []))
    with sqlite3.connect(str(config.database)) as connection:
        if entity_ids or user_ids:
            values = entity_ids + user_ids
            placeholders = ",".join("?" for _ in values)
            connection.execute("DELETE FROM audit_logs WHERE entity_id IN (%s) OR actor_id IN (%s)" % (placeholders, placeholders), values + values)
        for table, ids in (("tasks", created.get("task_ids", [])), ("cats", created.get("cat_ids", [])), ("media_assets", created.get("media_ids", [])), ("communities", created.get("community_ids", []))):
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute("DELETE FROM %s WHERE id IN (%s)" % (table, placeholders), list(ids))
        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            connection.execute("DELETE FROM daily_cat_quotas WHERE user_id IN (%s)" % placeholders, user_ids)
            connection.execute("DELETE FROM sessions WHERE user_id IN (%s)" % placeholders, user_ids)
            connection.execute("DELETE FROM users WHERE id IN (%s)" % placeholders, user_ids)
        connection.commit()
    for object_key in created.get("object_keys", []):
        target = config.storage_root / object_key
        if target.is_file():
            target.unlink()


def _record_entity(created, section, item):
    created["entity_ids"].append(item["id"])
    created[section].append(item["id"])
    return item


def seed_full_flow(config, passwords):
    config = SeedConfig(
        base_url=config.base_url,
        database=Path(config.database),
        storage_root=Path(config.storage_root),
        manifest=Path(config.manifest),
        credentials=Path(config.credentials),
    )
    if set(passwords) != set(qa_accounts()) or any(len(value) < 12 for value in passwords.values()) or len(set(passwords.values())) != 3:
        raise ValueError("three unique QA passwords of at least 12 characters are required")
    _database_preflight(config)
    client = ApiClient(config.base_url)
    created = {
        "user_ids": [], "entity_ids": [], "community_ids": [], "cat_ids": [], "task_ids": [], "media_ids": [], "object_keys": []
    }
    tokens = {}
    users = {}
    super_token = None
    try:
        for key, account in qa_accounts().items():
            response = client.json(
                "POST", "/api/v1/auth/register",
                {"username": account["username"], "password": passwords[key]}, expected=201,
            )
            tokens[key] = response["access_token"]
            users[key] = {"id": response["user"]["id"], "username": account["username"], "role": account["role"]}
            created["user_ids"].append(response["user"]["id"])

        super_token = _temporary_super_session(config.database)
        promoted = client.json(
            "POST", "/api/v1/admin/users/%s/role" % users["admin"]["id"],
            {"role": "ADMIN"}, token=super_token,
        )
        if promoted.get("role") != "ADMIN":
            raise RuntimeError("QA administrator promotion failed")

        entities = expected_entities()
        communities = {}
        communities["active"] = _record_entity(created, "community_ids", client.json(
            "POST", "/api/v1/communities", {"name": entities["communities"]["active"]["name"], "street": "银湖街道"}, tokens["admin"], 201,
        ))
        communities["pending"] = _record_entity(created, "community_ids", client.json(
            "POST", "/api/v1/communities", {"name": entities["communities"]["pending"]["name"], "street": "银湖街道"}, tokens["user_a"], 201,
        ))
        communities["hidden"] = _record_entity(created, "community_ids", client.json(
            "POST", "/api/v1/communities", {"name": entities["communities"]["hidden"]["name"], "street": "银湖街道"}, tokens["user_b"], 201,
        ))
        communities["hidden"] = client.json(
            "POST", "/api/v1/communities/%s/review" % communities["hidden"]["id"], {"approved": False}, tokens["admin"],
        )
        communities["archived"] = _record_entity(created, "community_ids", client.json(
            "POST", "/api/v1/communities", {"name": entities["communities"]["archived"]["name"], "street": "银湖街道"}, tokens["admin"], 201,
        ))
        communities["archived"] = client.json("POST", "/api/v1/communities/%s/archive" % communities["archived"]["id"], token=tokens["admin"])

        def create_cat(key, actor, location, health="良好", photo_asset_id=None):
            payload = {
                "community_id": communities["active"]["id"], "nickname": entities["cats"][key]["name"],
                "location_note": location, "living_status": "社区散养", "health_status": health,
                "latitude": 30.123 + len(created["cat_ids"]) * 0.001, "longitude": 119.987 + len(created["cat_ids"]) * 0.001,
            }
            if photo_asset_id:
                payload["photo_asset_id"] = photo_asset_id
            return _record_entity(created, "cat_ids", client.json("POST", "/api/v1/cats", payload, tokens[actor], 201))

        cats = {}
        cats["pending"] = create_cat("pending", "user_a", "1号楼花坛")
        cats["public"] = create_cat("public", "user_a", "东门岗亭")
        cats["public"] = client.json("POST", "/api/v1/cats/%s/review" % cats["public"]["id"], {"approved": True}, tokens["admin"])
        cats["rejected"] = create_cat("rejected", "user_a", "信息待核实")
        cats["rejected"] = client.json("POST", "/api/v1/cats/%s/review" % cats["rejected"]["id"], {"approved": False}, tokens["admin"])
        cats["hidden"] = create_cat("hidden", "user_b", "儿童乐园", "需要观察")
        cats["hidden"] = client.json("POST", "/api/v1/cats/%s/review" % cats["hidden"]["id"], {"approved": True}, tokens["admin"])
        cats["hidden"] = client.json("POST", "/api/v1/cats/%s/visibility" % cats["hidden"]["id"], {"visible": False}, tokens["admin"])
        cats["archived"] = create_cat("archived", "user_b", "旧停车棚")
        cats["archived"] = client.json("POST", "/api/v1/cats/%s/review" % cats["archived"]["id"], {"approved": True}, tokens["admin"])
        cats["archived"] = client.json("POST", "/api/v1/cats/%s/archive" % cats["archived"]["id"], token=tokens["admin"])

        media = client.upload_jpeg("/api/v1/media/images", b"\xff\xd8\xff\xe0HelpCat-QA-JPEG", tokens["admin"])
        created["entity_ids"].append(media["id"])
        created["media_ids"].append(media["id"])
        created["object_keys"].append(media["object_key"])
        cats["admin_photo"] = create_cat("admin_photo", "admin", "社区服务站", photo_asset_id=media["id"])
        if not client.bytes("/api/v1/media/%s" % media["id"]).startswith(b"\xff\xd8\xff"):
            raise RuntimeError("QA media readback failed")

        tasks = {}
        for key in ("open", "claimed"):
            tasks[key] = _record_entity(created, "task_ids", client.json(
                "POST", "/api/v1/tasks",
                {"title": entities["tasks"][key]["name"], "description": "%s 全流程测试任务" % PREFIX, "community_id": communities["active"]["id"]},
                tokens["admin"], 201,
            ))
        tasks["claimed"] = client.json("POST", "/api/v1/tasks/%s/claim" % tasks["claimed"]["id"], token=tokens["user_a"])

        public_communities = client.json("GET", "/api/v1/communities")["items"]
        public_cats = client.json("GET", "/api/v1/cats")["items"]
        public_tasks = client.json("GET", "/api/v1/tasks")["items"]
        if {item["name"] for item in public_communities if item["name"].startswith(PREFIX)} != {entities["communities"]["active"]["name"]}:
            raise RuntimeError("public community visibility verification failed")
        if {item["nickname"] for item in public_cats if item["nickname"].startswith(PREFIX)} != {entities["cats"]["public"]["name"], entities["cats"]["admin_photo"]["name"]}:
            raise RuntimeError("public cat visibility verification failed")
        if {item["title"] for item in public_tasks if item["title"].startswith(PREFIX)} != {entities["tasks"]["open"]["name"]}:
            raise RuntimeError("public task visibility verification failed")

        admin_users = client.json("GET", "/api/v1/admin/users", token=super_token)["items"]
        actual_roles = {item["username"]: item["role"] for item in admin_users if item.get("username") in {value["username"] for value in qa_accounts().values()}}
        if actual_roles != {value["username"]: value["role"] for value in qa_accounts().values()}:
            raise RuntimeError("QA user role verification failed")

        with sqlite3.connect(str(config.database)) as connection:
            audited_entity_ids = created["entity_ids"] + created["user_ids"]
            audit_actions = sorted({row[0] for row in connection.execute(
                "SELECT action FROM audit_logs WHERE entity_id IN (%s) OR actor_id IN (%s)" % (
                    ",".join("?" for _ in audited_entity_ids), ",".join("?" for _ in created["user_ids"])
                ), audited_entity_ids + created["user_ids"]
            )})
            supers = connection.execute("SELECT username, role, status FROM users WHERE role = 'SUPER_ADMIN'").fetchall()
        if not REQUIRED_AUDIT_ACTIONS.issubset(set(audit_actions)):
            missing_actions = sorted(REQUIRED_AUDIT_ACTIONS - set(audit_actions))
            raise RuntimeError("QA audit coverage verification failed: missing=%s actual=%s" % (missing_actions, audit_actions))
        if supers != [("zack", "SUPER_ADMIN", "ACTIVE")]:
            raise RuntimeError("unique SUPER_ADMIN invariant failed after seed")

        manifest = {
            "batch": BATCH, "prefix": PREFIX, "created_at": datetime.now(timezone.utc).isoformat(),
            "users": users,
            "communities": {key: {"id": item["id"], "name": item["name"], "status": item["status"]} for key, item in communities.items()},
            "cats": {key: {"id": item["id"], "name": item["nickname"], "review_status": item["review_status"], "visibility_status": item["visibility_status"]} for key, item in cats.items()},
            "tasks": {key: {"id": item["id"], "name": item["title"], "status": item["status"]} for key, item in tasks.items()},
            "media": {"id": media["id"], "object_key": media["object_key"]},
            "audit_actions": audit_actions,
            "super_admin": {"count": 1, "username": "zack", "role": "SUPER_ADMIN"},
        }
        validate_manifest(manifest)
        _atomic_private_write(config.manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        credential_lines = ["batch=%s" % BATCH]
        for key, account in qa_accounts().items():
            credential_lines.extend(["", "role=%s" % key, "username=%s" % account["username"], "password=%s" % passwords[key]])
        _atomic_private_write(config.credentials, "\n".join(credential_lines) + "\n")
        return manifest
    except Exception:
        _rollback_partial(config, created)
        if config.manifest.exists():
            config.manifest.unlink()
        if config.credentials.exists():
            config.credentials.unlink()
        raise
    finally:
        _remove_session(config.database, super_token)


def _generated_passwords():
    return {key: secrets.token_urlsafe(20) + "!" for key in qa_accounts()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    arguments = parser.parse_args(argv)
    config = SeedConfig(arguments.base_url, arguments.database, arguments.storage_root, arguments.manifest, arguments.credentials)
    manifest = seed_full_flow(config, _generated_passwords())
    print(json.dumps({
        "status": "ok", "batch": manifest["batch"],
        "users": len(manifest["users"]), "communities": len(manifest["communities"]),
        "cats": len(manifest["cats"]), "tasks": len(manifest["tasks"]),
        "manifest": str(arguments.manifest), "credentials": str(arguments.credentials),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
