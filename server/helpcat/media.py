"""图片处理：安全解码/重编码、缩略图、以及交给 nginx 直出的响应。

公开图片必须先完整解码再重新编码，顺带丢掉 EXIF/GPS；列表缩略图单独落一个
`.thumb.webp`，不改动原图。读取路径优先走 `X-Accel-Redirect`，让 nginx 读字节，
FastAPI 只负责鉴权与存在性检查。
"""

import io
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Response
from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import error

PUBLIC_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}

# Pillow 报出来、但和某个对外格式等价的内置格式。
# MPO 是手机相机的 HDR / 人像 / 连拍照片：本质就是带多帧的 JPEG，Pillow 的
# `format` 却是 "MPO"。不认它的时候，用户从手机相册选照片就会拿到
# 「图片内容无法识别」（线上真实反馈过一次）。
DECODED_FORMAT_ALIASES = {
    "MPO": "JPEG",
}

# 有些系统/浏览器会报非标准 MIME，含义和标准类型一样。
CLAIMED_CONTENT_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
    "image/x-webp": "image/webp",
}

# 这两种表示"没告诉我们类型"，此时以解码出来的真实格式为准（部分安卓/微信选择器
# 就是这么发的），而不是直接拒掉。
BLANK_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}


def normalize_claimed_content_type(value):
    """把客户端声明的 MIME 归一化；认不出/没给时返回空串。"""
    claimed = (value or "").strip().lower()
    if claimed in BLANK_CONTENT_TYPES:
        return ""
    return CLAIMED_CONTENT_TYPE_ALIASES.get(claimed, claimed)
MEDIA_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
MEDIA_ACCEL_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}
MEDIA_THUMBNAIL_SIZE = 640


def media_thumbnail_path(storage_root, object_key):
    return storage_root / (Path(object_key).stem + ".thumb.webp")


def media_accel_path(prefix, object_key):
    """nginx internal URL for one stored object, each segment URL-quoted.

    Sub-directories (and non-ASCII names) survive the header round-trip while a
    segment can never inject `/` or `..` into the location nginx serves.
    """
    quoted = "/".join(quote(segment, safe="") for segment in str(object_key).split("/"))
    return prefix + "/" + quoted


def accel_media_response(prefix, object_key, media_type):
    """Hand the file send to nginx: FastAPI decides access, nginx reads bytes."""
    return Response(
        status_code=200,
        media_type=media_type,
        headers={**MEDIA_ACCEL_CACHE_HEADERS, "X-Accel-Redirect": media_accel_path(prefix, object_key)},
    )


def create_media_thumbnail(source_path, target_path):
    """Create a small, metadata-free list thumbnail without changing the original asset."""
    with Image.open(source_path) as source:
        thumbnail = ImageOps.exif_transpose(source).convert("RGB")
        thumbnail.thumbnail((MEDIA_THUMBNAIL_SIZE, MEDIA_THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        thumbnail.save(output, format="WEBP", quality=76, method=6)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary_path.write_bytes(output.getvalue())
    temporary_path.replace(target_path)


def sanitize_public_image(content, claimed_content_type, max_image_pixels, max_image_bytes):
    """Fully decode and safely re-encode one public image without source metadata.

    输出格式由**解码结果**决定，`claimed_content_type` 只用来做一致性校验：
    认不出的类型直接说清楚"这张到底是什么格式"，类型对不上则报 mismatch。
    """
    claimed = normalize_claimed_content_type(claimed_content_type)
    try:
        with Image.open(io.BytesIO(content)) as source:
            decoded_format = source.format
            # 归一化之后再查白名单和走重编码分支：MPO 必须当作 JPEG 走 JPEG 分支，
            # 否则字节会被存成 WebP，而 content_type 报的是 image/jpeg。
            image_format = DECODED_FORMAT_ALIASES.get(decoded_format, decoded_format)
            expected = PUBLIC_IMAGE_FORMATS.get(image_format)
            if not expected:
                # 别只说"无法识别"：把真实格式和可行的替代做法告诉用户。
                error(415, "unsupported_image_format",
                      "这张图片实际是 %s 格式，只支持 JPEG / PNG / WebP。可以先截图再上传。" % (decoded_format or "未知"))
            if claimed and expected[0] != claimed:
                error(415, "image_content_mismatch")
            frame_count = int(getattr(source, "n_frames", 1) or 1)
            decoded_pixels = source.width * source.height * frame_count
            if decoded_pixels > max_image_pixels:
                error(413, "image_too_many_pixels")
            for frame_index in range(frame_count):
                source.seek(frame_index)
                source.load()
            source.seek(0)
            sanitized = ImageOps.exif_transpose(source)
            if image_format == "JPEG":
                if sanitized.mode not in {"RGB", "L"}:
                    sanitized = sanitized.convert("RGB")
            elif sanitized.mode not in {"RGB", "RGBA", "L", "LA"}:
                sanitized = sanitized.convert("RGBA" if "transparency" in source.info else "RGB")
            output = io.BytesIO()
            if image_format == "JPEG":
                sanitized.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
            elif image_format == "PNG":
                sanitized.save(output, format="PNG", optimize=True, compress_level=9)
            else:
                sanitized.save(output, format="WEBP", quality=85, method=6)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError):
        error(415, "image_content_mismatch")
    sanitized_content = output.getvalue()
    if len(sanitized_content) > max_image_bytes:
        error(413, "image_too_large")
    return sanitized_content, expected[0], expected[1]
