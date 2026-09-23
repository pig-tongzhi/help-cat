"""图片上传与读取。"""

from ..dependencies import get_current_user, get_db
from ..errors import error
from ..media import MEDIA_CACHE_HEADERS, PUBLIC_IMAGE_FORMATS, accel_media_response, create_media_thumbnail, media_thumbnail_path, normalize_claimed_content_type, sanitize_public_image
from ..models import MediaAsset, new_id
from ..serializers import audit
from fastapi import APIRouter
from fastapi import Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession


router = APIRouter()


@router.post("/api/v1/media/images", status_code=201)
async def upload_image(request: Request, file: UploadFile = File(...), actor=Depends(get_current_user), db: DbSession = Depends(get_db)):
    allowed_content_types = {item[0] for item in PUBLIC_IMAGE_FORMATS.values()}
    claimed_content_type = normalize_claimed_content_type(file.content_type)
    # 没给类型（空 / octet-stream）不算错，交给解码结果判断；给了类型就必须在白名单里。
    if claimed_content_type and claimed_content_type not in allowed_content_types:
        error(415, "unsupported_image_type")
    content = await file.read(request.app.state.settings.max_image_bytes + 1)
    if len(content) > request.app.state.settings.max_image_bytes:
        error(413, "image_too_large")
    sanitized, content_type, extension = sanitize_public_image(
        content, file.content_type, request.app.state.settings.max_image_pixels, request.app.state.settings.max_image_bytes,
    )
    asset = MediaAsset(object_key=new_id() + extension, content_type=content_type, byte_size=len(sanitized), created_by=actor[0])
    target = request.app.state.settings.storage_root / asset.object_key
    target.write_bytes(sanitized)
    try:
        create_media_thumbnail(target, media_thumbnail_path(request.app.state.settings.storage_root, asset.object_key))
    except OSError:
        target.unlink(missing_ok=True)
        error(500, "thumbnail_generation_failed")
    db.add(asset)
    db.flush()
    audit(db, actor[0], "UPLOAD", "media", asset.id, after={"content_type": asset.content_type, "byte_size": asset.byte_size})
    db.commit()
    return {"id": asset.id, "object_key": asset.object_key, "content_type": asset.content_type, "byte_size": asset.byte_size}


@router.get("/api/v1/media/{asset_id}")
def get_media(request: Request, asset_id: str, variant: str = Query(default="original", pattern="^(original|thumb)$"), db: DbSession = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        error(404, "media_not_found")
    path = request.app.state.settings.storage_root / asset.object_key
    if not path.is_file():
        error(404, "media_file_not_found")
    if variant == "thumb":
        thumbnail_path = media_thumbnail_path(request.app.state.settings.storage_root, asset.object_key)
        if not thumbnail_path.is_file():
            try:
                create_media_thumbnail(path, thumbnail_path)
            except OSError:
                error(500, "thumbnail_generation_failed")
        if request.app.state.settings.media_accel_prefix:
            return accel_media_response(request.app.state.settings.media_accel_prefix, thumbnail_path.relative_to(request.app.state.settings.storage_root), "image/webp")
        return FileResponse(thumbnail_path, media_type="image/webp", headers=MEDIA_CACHE_HEADERS)
    if request.app.state.settings.media_accel_prefix:
        return accel_media_response(request.app.state.settings.media_accel_prefix, path.relative_to(request.app.state.settings.storage_root), asset.content_type)
    return FileResponse(path, media_type=asset.content_type, headers=MEDIA_CACHE_HEADERS)
