#!/usr/bin/env python3
"""Idempotently import the approved public profile for 77 through the Help Cat API."""

import argparse
import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


MARKER = "2025-06-02 相遇"
LOCATION_NOTE = "公开位置已保护；" + MARKER


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

    def upload_image(self, path, token, expected=201):
        content = Path(path).read_bytes()
        boundary = "----HelpCat77%s" % secrets.token_hex(12)
        filename = Path(path).name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body = (
            ("--%s\r\n" % boundary).encode()
            + ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename).encode()
            + ("Content-Type: %s\r\n\r\n" % content_type).encode()
            + content
            + ("\r\n--%s--\r\n" % boundary).encode()
        )
        request = urllib.request.Request(
            self.base_url + "/api/v1/media/images",
            data=body,
            headers={"Authorization": "Bearer " + token, "Content-Type": "multipart/form-data; boundary=" + boundary},
            method="POST",
        )
        status, response = self._open(request)
        if status != expected:
            code = response.get("code") if isinstance(response, dict) else "invalid_response"
            raise RuntimeError("POST /api/v1/media/images returned %s (%s)" % (status, code))
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


def _find_marked_cat(client, token):
    for visibility_token in (None, token):
        cursor = None
        while True:
            parameters = {"q": "77"}
            if cursor:
                parameters["cursor"] = cursor
            response = client.json("GET", "/api/v1/cats?" + urllib.parse.urlencode(parameters), token=visibility_token)
            for item in response.get("items", []):
                if item.get("nickname") == "77" and MARKER in item.get("location_note", ""):
                    return item
            cursor = response.get("next_cursor")
            if not cursor:
                break
    return None


def seed_77_profile(config, client=None):
    """Create or repair the approved public 77 profile without duplicating its cat or media."""
    password = _require_password(config.password_env)
    client = client or ApiClient(config.base_url)
    login = client.json("POST", "/api/v1/auth/login", {"username": config.username, "password": password})
    token = login.get("access_token")
    if not token:
        raise RuntimeError("login response did not include an access token")
    account = client.json("GET", "/api/v1/auth/me", token=token)
    if account.get("role") not in {"ADMIN", "SUPER_ADMIN"}:
        raise RuntimeError("77 profile import requires an ADMIN or SUPER_ADMIN account")

    cat = _find_marked_cat(client, token)
    changed = False
    if not cat:
        media = client.upload_image(config.photo, token)
        media_id = media.get("id")
        if not media_id:
            raise RuntimeError("image upload response did not include a media id")
        cat = client.json("POST", "/api/v1/cats", {
            "community_id": config.community_id,
            "nickname": "77",
            "living_status": "已进入家庭",
            "health_status": "UNKNOWN",
            "location_note": LOCATION_NOTE,
            "photo_asset_id": media_id,
        }, token=token, expected=201)
        changed = True
    media_id = cat.get("photo_asset_id")
    if not media_id:
        raise RuntimeError("existing 77 profile has no approved portrait media")
    if cat.get("review_status") == "PENDING_REVIEW":
        cat = client.json("POST", "/api/v1/cats/%s/review" % cat["id"], {"approved": True}, token=token)
        changed = True
    elif cat.get("review_status") != "APPROVED":
        raise RuntimeError("existing 77 profile requires manual review")
    if cat.get("visibility_status") == "HIDDEN":
        client.json("POST", "/api/v1/cats/%s/visibility" % cat["id"], {"visible": True}, token=token)
        changed = True
    elif cat.get("visibility_status") != "ACTIVE":
        raise RuntimeError("existing 77 profile requires manual review")
    return {"cat_id": cat["id"], "media_id": media_id, "changed": changed}


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
