#!/usr/bin/env python3
"""Idempotently import 77 as a hidden draft through the Help Cat API."""

import argparse
import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


MARKER = "2025-06-02 相遇"
LOCATION_NOTE = "公开位置已保护；" + MARKER
PROFILE_KEY = "story-77"
IDEMPOTENCY_KEY = "help-cat:profile:story-77:import:v1"


@dataclass(frozen=True)
class SeedConfig:
    base_url: str
    username: str
    password_env: str
    community_id: str
    photo: Path


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

    def import_cat_draft(self, path, token, fields, idempotency_key, expected=201):
        content = Path(path).read_bytes()
        boundary = "----HelpCat77%s" % secrets.token_hex(12)
        parts = []
        for name, value in fields.items():
            parts.append((
                "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (boundary, name, value)
            ).encode("utf-8"))
        filename = Path(path).name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(
            ("--%s\r\n" % boundary).encode()
            + ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename).encode()
            + ("Content-Type: %s\r\n\r\n" % content_type).encode()
            + content
            + b"\r\n"
        )
        parts.append(("--%s--\r\n" % boundary).encode())
        request = urllib.request.Request(
            self.base_url + "/api/v1/admin/cat-drafts/import",
            data=b"".join(parts),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "multipart/form-data; boundary=" + boundary,
                "Idempotency-Key": idempotency_key,
            },
            method="POST",
        )
        status, response = self._open(request)
        if status != expected:
            code = response.get("code") if isinstance(response, dict) else "invalid_response"
            raise RuntimeError("POST /api/v1/admin/cat-drafts/import returned %s (%s)" % (status, code))
        return response

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


def _require_password(password_env):
    password = os.environ.get(password_env)
    if not password:
        raise RuntimeError("required password environment variable is not set: %s" % password_env)
    return password


def seed_77_profile(config, client=None):
    """Atomically import 77 as a hidden draft; publication always remains manual."""
    password = _require_password(config.password_env)
    client = client or ApiClient(config.base_url)
    login = client.json("POST", "/api/v1/auth/login", {"username": config.username, "password": password})
    token = login.get("access_token")
    if not token:
        raise RuntimeError("login response did not include an access token")
    account = client.json("GET", "/api/v1/auth/me", token=token)
    if account.get("role") not in {"ADMIN", "SUPER_ADMIN"}:
        raise RuntimeError("77 profile import requires an ADMIN or SUPER_ADMIN account")

    result = client.import_cat_draft(config.photo, token, {
        "community_id": config.community_id,
        "profile_key": PROFILE_KEY,
        "nickname": "77",
        "living_status": "已进入家庭",
        "health_status": "UNKNOWN",
        "location_note": LOCATION_NOTE,
    }, IDEMPOTENCY_KEY, expected=201)
    cat = result.get("cat") or {}
    media = result.get("media") or {}
    media_id = media.get("id") or cat.get("photo_asset_id")
    if not cat.get("id") or not media_id:
        raise RuntimeError("draft import response did not include cat and media ids")
    if cat.get("profile_key") != PROFILE_KEY:
        raise RuntimeError("draft import returned an unexpected profile key")
    if cat.get("review_status") == "REJECTED" or cat.get("visibility_status") == "ARCHIVED":
        raise RuntimeError("existing 77 profile requires manual review")
    return {"cat_id": cat["id"], "media_id": media_id, "changed": bool(result.get("changed"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-env", required=True)
    parser.add_argument("--community-id", required=True)
    parser.add_argument("--photo", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = seed_77_profile(SeedConfig(
        base_url=arguments.base_url,
        username=arguments.username,
        password_env=arguments.password_env,
        community_id=arguments.community_id,
        photo=arguments.photo,
    ))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
