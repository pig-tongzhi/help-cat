"""P0 架构修复的行为断言：图片交给 nginx、SQLite 打开 WAL。

两件事都发生在基础设施边界上，所以这里用真实 ASGI 请求而不是 mock：

* `GET /api/v1/media/{id}` 在配置了 `HELPCAT_MEDIA_ACCEL_PREFIX` 时只回一个空的
  `X-Accel-Redirect`（文件由 nginx 读），未配置时仍然由 FastAPI 原样回字节。
  鉴权/存在性检查必须留在 FastAPI，先于这行 302 式的委派。
* SQLite 的每条新连接都要带 `journal_mode=WAL` / `busy_timeout=5000` /
  `synchronous=NORMAL`；`:memory:` 上 WAL 是 no-op，但不能因此报错。
"""

import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote, urlsplit

from PIL import Image
from sqlalchemy import text

from server.helpcat.app import create_app
from server.helpcat.db import ensure_schema, make_session_factory
from server.helpcat.models import MediaAsset


class MediaAccelAndSqliteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 脚手架（与 server/tests 的其它 API 测试保持一致） ----------------

    def build_app(self, accel_prefix=None, storage_root=None):
        """Build the app with the media env the case needs.

        `accel_prefix=None` means "unset" (not "empty string"), so the streaming
        branch is exercised even when the developer's shell exports a prefix.
        """
        environment = {"HELPCAT_MEDIA_ACCEL_PREFIX": accel_prefix} if accel_prefix is not None else {}
        with mock.patch.dict(os.environ, environment, clear=False):
            if accel_prefix is None:
                os.environ.pop("HELPCAT_MEDIA_ACCEL_PREFIX", None)
            return create_app("sqlite://", storage_root or self.storage_root, fake_admin_openids={"admin-openid"})

    def request_raw(self, app, method, path, token=None, payload=None, file_tuple=None):
        headers, body = self.build_request(token, payload, file_tuple)
        return asyncio.run(self.asgi_request(app, method, path, headers, body))

    def request_on(self, app, method, path, token=None, payload=None, file_tuple=None):
        status, _, content = self.request_raw(app, method, path, token, payload, file_tuple)
        return status, (json.loads(content.decode()) if content else {})

    @staticmethod
    def build_request(token, payload, file_tuple):
        headers = {}
        body = None
        if token:
            headers["Authorization"] = "Bearer " + token
        if file_tuple:
            boundary = "----HelpCatMediaBoundary"
            filename, content, content_type = file_tuple
            body = (
                "--" + boundary + "\r\n"
                "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n"
                "Content-Type: " + content_type + "\r\n\r\n"
            ).encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return headers, body

    async def asgi_request(self, app, method, path, headers, body):
        parsed = urlsplit(path)
        sent = False
        messages = []

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body or b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "http_version": "1.1", "method": method, "path": parsed.path,
            "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": ("testclient", 50000), "server": ("testserver", 80), "scheme": "http",
        }
        await app(scope, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        response_headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return start["status"], response_headers, content

    def login(self, app, openid):
        status, body = self.request_on(app, "POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(status, 200)
        return body

    @staticmethod
    def jpeg_bytes(size=(8, 8)):
        image = Image.new("RGB", size, (231, 220, 205))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()

    def upload_image(self, app, token, filename="cat.jpg"):
        status, asset = self.request_on(
            app, "POST", "/api/v1/media/images", token=token,
            file_tuple=(filename, self.jpeg_bytes(), "image/jpeg"),
        )
        self.assertEqual(status, 201)
        return asset

    def seed_asset(self, app, object_key, created_by, content=None, content_type="image/jpeg"):
        """Write one stored object directly, to exercise keys the uploader never makes."""
        content = self.jpeg_bytes() if content is None else content
        target = app.state.settings.storage_root / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        with app.state.session_factory() as db:
            asset = MediaAsset(object_key=object_key, content_type=content_type, byte_size=len(content), created_by=created_by)
            db.add(asset)
            db.commit()
            return asset.id

    # ---- nginx 直出 ----------------------------------------------------

    def test_accel_prefix_returns_empty_body_and_the_nginx_header(self):
        app = self.build_app(accel_prefix="/__media")
        admin = self.login(app, "admin-openid")
        asset = self.upload_image(app, admin["access_token"])

        status, headers, content = self.request_raw(app, "GET", "/api/v1/media/" + asset["id"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["x-accel-redirect"], "/__media/" + asset["object_key"])
        self.assertEqual(headers["content-type"], asset["content_type"])
        self.assertEqual(headers["cache-control"], "public, max-age=604800")
        self.assertEqual(content, b"")

    def test_accel_prefix_covers_the_thumbnail_variant(self):
        app = self.build_app(accel_prefix="/__media")
        admin = self.login(app, "admin-openid")
        asset = self.upload_image(app, admin["access_token"])

        status, headers, content = self.request_raw(app, "GET", "/api/v1/media/%s?variant=thumb" % asset["id"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["x-accel-redirect"], "/__media/" + Path(asset["object_key"]).stem + ".thumb.webp")
        self.assertEqual(headers["content-type"], "image/webp")
        self.assertEqual(content, b"")

    def test_accel_prefix_does_not_bypass_the_fastapi_checks(self):
        # The route is public by asset id, so the checks that must stay in FastAPI
        # are existence checks. They have to fail identically with and without the
        # accel prefix: a missing / QA asset is never handed to nginx.
        for accel_prefix in ("/__media", None):
            app = self.build_app(accel_prefix=accel_prefix)
            admin = self.login(app, "admin-openid")
            asset = self.upload_image(app, admin["access_token"])

            status, headers, content = self.request_raw(app, "GET", "/api/v1/media/missing-asset")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(content.decode())["code"], "media_not_found")
            self.assertNotIn("x-accel-redirect", headers)

            (app.state.settings.storage_root / asset["object_key"]).unlink()
            status, headers, content = self.request_raw(app, "GET", "/api/v1/media/" + asset["id"])
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(content.decode())["code"], "media_file_not_found")
            self.assertNotIn("x-accel-redirect", headers)

    def test_accel_prefix_quotes_subdirectories_and_non_ascii_keys(self):
        app = self.build_app(accel_prefix="/__media")
        admin = self.login(app, "admin-openid")
        object_key = "cats/2026/猫咪 相册.jpg"
        asset_id = self.seed_asset(app, object_key, admin["user"]["id"])

        status, headers, content = self.request_raw(app, "GET", "/api/v1/media/" + asset_id)
        self.assertEqual(status, 200)
        self.assertEqual(
            headers["x-accel-redirect"],
            "/__media/cats/2026/%E7%8C%AB%E5%92%AA%20%E7%9B%B8%E5%86%8C.jpg",
        )
        self.assertEqual(headers["x-accel-redirect"], "/__media/cats/2026/" + quote("猫咪 相册.jpg", safe=""))
        self.assertEqual(content, b"")

    def test_without_the_accel_prefix_fastapi_still_streams_the_bytes(self):
        app = self.build_app(accel_prefix=None)
        admin = self.login(app, "admin-openid")
        asset = self.upload_image(app, admin["access_token"])

        status, headers, content = self.request_raw(app, "GET", "/api/v1/media/" + asset["id"])
        self.assertEqual(status, 200)
        self.assertNotIn("x-accel-redirect", headers)
        self.assertEqual(headers["content-type"], asset["content_type"])
        self.assertEqual(headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertEqual(content, (app.state.settings.storage_root / asset["object_key"]).read_bytes())
        self.assertGreater(len(content), 0)

    # ---- SQLite PRAGMA -------------------------------------------------

    def test_file_backed_sqlite_connections_open_in_wal_with_a_busy_timeout(self):
        database_path = Path(self.tmp.name) / "help-cat.db"
        engine, _ = make_session_factory("sqlite:///" + str(database_path))
        try:
            ensure_schema(engine)
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("PRAGMA journal_mode")).scalar(), "wal")
                self.assertEqual(connection.execute(text("PRAGMA busy_timeout")).scalar(), 5000)
                self.assertEqual(connection.execute(text("PRAGMA synchronous")).scalar(), 1)
            # A brand new DBAPI connection must get the same pragmas, not just the first.
            engine.dispose()
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("PRAGMA journal_mode")).scalar(), "wal")
                self.assertEqual(connection.execute(text("PRAGMA busy_timeout")).scalar(), 5000)
        finally:
            engine.dispose()

    def test_in_memory_app_still_serves_reads_and_writes(self):
        app = self.build_app(accel_prefix=None)
        status, body = self.request_on(app, "GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

        admin = self.login(app, "admin-openid")
        status, community = self.request_on(
            app, "POST", "/api/v1/communities", token=admin["access_token"],
            payload={"name": "内存小区", "street": "银湖街道"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(community["status"], "ACTIVE")

        status, body = self.request_on(app, "GET", "/api/v1/communities")
        self.assertEqual(status, 200)
        self.assertIn(community["id"], [item["id"] for item in body["items"]])


if __name__ == "__main__":
    unittest.main()
