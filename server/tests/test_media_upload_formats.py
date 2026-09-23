"""上传图片的格式判定。

线上真实反馈：建档时选手机相册里的照片，界面报「图片内容无法识别」。原因是白名单里
只有 JPEG / PNG / WEBP，而**手机相机的 HDR / 人像 / 连拍照片常常是 MPO** —— 它本质
就是带多帧的 JPEG，Pillow 却把 format 报成 "MPO"，于是撞上 `image_content_mismatch`。

这里把「什么该收、什么该拒、拒了要说什么」都钉住：

* MPO / 多帧 JPEG 按 JPEG 收，并且落库时只保留单帧；
* 系统报的非标准 MIME（`image/jpg`）等价于标准类型；
* 选择器没给 MIME（空串 / octet-stream）时不拦，按解码结果判断；
* 真正不支持的格式（GIF、HEIC…）要说清楚"这张实际是什么格式"，而不是一句"无法识别"；
* 声明类型和真实内容对不上（PNG 内容却报 image/jpeg）仍然是错误，但文案要能指导用户。
"""

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw
from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.media import PUBLIC_IMAGE_FORMATS, normalize_claimed_content_type, sanitize_public_image
from server.helpcat.models import MediaAsset


def jpeg_bytes(color=(231, 220, 205), size=(64, 48)):
    image = Image.new("RGB", size, color)
    ImageDraw.Draw(image).ellipse((6, 6, 40, 40), fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def png_bytes(size=(64, 48)):
    image = Image.new("RGB", size, (200, 210, 220))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def gif_bytes(size=(64, 48)):
    image = Image.new("P", size)
    buffer = io.BytesIO()
    image.save(buffer, format="GIF")
    return buffer.getvalue()


def mpo_bytes(size=(64, 48)):
    """手机相机那种多帧 JPEG：Pillow 会把 format 报成 MPO。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, (240, 180, 120)).save(
        buffer, format="MPO", save_all=True, append_images=[Image.new("RGB", size, (30, 30, 30))]
    )
    return buffer.getvalue()


class SanitizerFormatTests(unittest.TestCase):
    """不经过 HTTP，直接测解码/重编码这一层。"""

    def sanitize(self, content, claimed):
        return sanitize_public_image(content, claimed, 40_000_000, 8_000_000)

    def test_mpo_is_treated_as_jpeg_and_flattened_to_one_frame(self):
        self.assertEqual("MPO", Image.open(io.BytesIO(mpo_bytes())).format, "前提：这份测试数据确实是 MPO")

        sanitized, content_type, extension = self.sanitize(mpo_bytes(), "image/jpeg")

        self.assertEqual("image/jpeg", content_type)
        self.assertEqual(".jpg", extension)
        with Image.open(io.BytesIO(sanitized)) as stored:
            self.assertEqual("JPEG", stored.format)
            self.assertEqual(1, int(getattr(stored, "n_frames", 1)), "落库的应该是单帧")

    def test_blank_and_alias_content_types_are_normalized(self):
        self.assertEqual("", normalize_claimed_content_type(""))
        self.assertEqual("", normalize_claimed_content_type("   "))
        self.assertEqual("", normalize_claimed_content_type("application/octet-stream"))
        self.assertEqual("image/jpeg", normalize_claimed_content_type("image/jpg"))
        self.assertEqual("image/jpeg", normalize_claimed_content_type("IMAGE/JPEG"))
        self.assertEqual("image/png", normalize_claimed_content_type("image/x-png"))

    def test_unsupported_format_names_itself_in_the_error(self):
        with self.assertRaises(Exception) as caught:
            self.sanitize(gif_bytes(), "image/gif")
        detail = caught.exception.detail
        self.assertEqual("unsupported_image_format", detail["code"])
        self.assertIn("GIF", detail["message"], "要告诉用户这张到底是什么格式")

    def test_declared_type_that_contradicts_the_bytes_is_still_rejected(self):
        with self.assertRaises(Exception) as caught:
            self.sanitize(png_bytes(), "image/jpeg")
        self.assertEqual("image_content_mismatch", caught.exception.detail["code"])

    def test_every_allowed_format_maps_to_a_public_content_type(self):
        self.assertEqual({"image/jpeg", "image/png", "image/webp"},
                         {value[0] for value in PUBLIC_IMAGE_FORMATS.values()})


class UploadEndpointFormatTests(unittest.TestCase):
    """走真实 ASGI 请求，确认接口层的收/拒与文案。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", storage_root=Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        status, body = self.request("POST", "/api/v1/auth/wechat-login", payload={"code": "fake:admin-openid"})
        self.assertEqual(200, status)
        self.token = body["access_token"]

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, method, path, payload=None, file_tuple=None, token=None):
        status, _headers, content = asyncio.run(
            self.asgi_request(method, path, payload, file_tuple, token or getattr(self, "token", None))
        )
        return status, (json.loads(content.decode()) if content else {})

    async def asgi_request(self, method, path, payload, file_tuple, token):
        headers, body = {}, None
        if token:
            headers["Authorization"] = "Bearer " + token
        if file_tuple:
            boundary = "----HelpCatFormatBoundary"
            filename, content, content_type = file_tuple
            body = (
                "--" + boundary + "\r\n"
                'Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n'
                "Content-Type: " + content_type + "\r\n\r\n"
            ).encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()

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
        await self.app(scope, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return start["status"], {}, content

    def upload(self, content, content_type, filename="photo.jpg"):
        return self.request("POST", "/api/v1/media/images", file_tuple=(filename, content, content_type))

    def stored_assets(self):
        with self.app.state.session_factory() as session:
            return list(session.scalars(select(MediaAsset)))

    def test_a_phone_mpo_photo_uploads_as_a_single_frame_jpeg(self):
        status, body = self.upload(mpo_bytes(), "image/jpeg")
        self.assertEqual(201, status, body)
        self.assertEqual("image/jpeg", body["content_type"])
        assets = self.stored_assets()
        self.assertEqual(1, len(assets))
        stored = self.app.state.settings.storage_root / assets[0].object_key
        with Image.open(stored) as image:
            self.assertEqual("JPEG", image.format)
            self.assertEqual(1, int(getattr(image, "n_frames", 1)))

    def test_alias_and_blank_content_types_are_accepted(self):
        for content_type in ("image/jpg", "", "application/octet-stream"):
            with self.subTest(content_type=content_type or "<empty>"):
                status, body = self.upload(jpeg_bytes(), content_type)
                self.assertEqual(201, status, body)
                self.assertEqual("image/jpeg", body["content_type"])

    def test_a_picker_that_reports_the_wrong_type_cannot_smuggle_a_png(self):
        status, body = self.upload(png_bytes(), "image/jpeg")
        self.assertEqual(415, status)
        self.assertEqual("image_content_mismatch", body["code"])

    def test_gif_explains_which_format_it_actually_is(self):
        # 用"没声明类型"的入口进来，才会走到解码分支拿到真实格式；
        # 明确声明 image/gif 会在入口就被挡掉（下面那条覆盖）。
        status, body = self.upload(gif_bytes(), "application/octet-stream")
        self.assertEqual(415, status)
        self.assertEqual("unsupported_image_format", body["code"])
        self.assertIn("GIF", body["message"])

    def test_a_known_but_unsupported_declared_type_is_rejected_early(self):
        for content_type in ("image/heic", "image/gif"):
            with self.subTest(content_type=content_type):
                status, body = self.upload(jpeg_bytes(), content_type)
                self.assertEqual(415, status)
                self.assertEqual("unsupported_image_type", body["code"])

    def test_a_thumbnail_is_written_for_the_mpo_upload(self):
        status, body = self.upload(mpo_bytes(), "image/jpeg")
        self.assertEqual(201, status, body)
        asset = self.stored_assets()[0]
        thumbnail = self.app.state.settings.storage_root / (Path(asset.object_key).stem + ".thumb.webp")
        self.assertTrue(thumbnail.exists(), "缩略图也要生成")


if __name__ == "__main__":
    unittest.main()
