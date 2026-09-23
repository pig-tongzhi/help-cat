import os
from pathlib import Path


class Settings:
    def __init__(self, database_url=None, storage_root=None, fake_admin_openids=None):
        self.database_url = database_url or os.getenv("HELPCAT_DATABASE_URL", "sqlite:///./data/help-cat.db")
        self.storage_root = Path(storage_root or os.getenv("HELPCAT_STORAGE_ROOT", "./data/uploads"))
        self.media_accel_prefix = os.getenv("HELPCAT_MEDIA_ACCEL_PREFIX", "")
        # 输入体积上限：手机原图（含 48MP 模式）通常在 20MB 以内；超出的先在前端压过一道。
        self.max_image_bytes = int(os.getenv("HELPCAT_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
        # 像素"硬上限"，只用来挡解压炸弹，不再当用户体验的坎：超过它才拒绝。
        # 108MP 手机照片（12000x9000）在范围内，真正的炸弹（几亿像素）会被挡住。
        self.max_image_pixels = int(os.getenv("HELPCAT_MAX_IMAGE_PIXELS", str(120 * 1024 * 1024)))
        # 长边超过这个值就自己缩小后再存，而不是拒绝用户。站内最大展示约 800px，
        # 1600px 足够清晰，同时把手机原图压到几百 KB。
        self.image_max_side = int(os.getenv("HELPCAT_IMAGE_MAX_SIDE", "1600"))
        self.session_days = int(os.getenv("HELPCAT_SESSION_DAYS", "30"))
        self.fake_admin_openids = set(fake_admin_openids or filter(None, os.getenv("HELPCAT_FAKE_ADMIN_OPENIDS", "").split(",")))
        self.wechat_app_id = os.getenv("HELPCAT_WECHAT_APP_ID", "")
        self.wechat_app_secret = os.getenv("HELPCAT_WECHAT_APP_SECRET", "")
        self.allowed_origins = [item for item in os.getenv("HELPCAT_ALLOWED_ORIGINS", "").split(",") if item]
        self.admin_usernames = set(filter(None, os.getenv("HELPCAT_ADMIN_USERNAMES", "").split(",")))
        # Public welcome page: how visitors reach the operator.
        self.admin_wechat = os.getenv("HELPCAT_ADMIN_WECHAT", "")
        self.admin_wechat_note = os.getenv("HELPCAT_ADMIN_WECHAT_NOTE", "帮帮小猫")
        self.admin_phone = os.getenv("HELPCAT_ADMIN_PHONE", "")
        self.admin_qr_image = os.getenv("HELPCAT_ADMIN_QR_IMAGE", "")
        self.admin_contact_note = os.getenv("HELPCAT_ADMIN_CONTACT_NOTE", "个人业余发起 · 有空时回复，不承诺随时响应")
        self.lead_rate_limit_per_hour = int(os.getenv("HELPCAT_LEAD_RATE_LIMIT_PER_HOUR", "10"))
        self.lead_dedupe_minutes = int(os.getenv("HELPCAT_LEAD_DEDUPE_MINUTES", "10"))
