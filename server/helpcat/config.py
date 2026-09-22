import os
from pathlib import Path


class Settings:
    def __init__(self, database_url=None, storage_root=None, fake_admin_openids=None):
        self.database_url = database_url or os.getenv("HELPCAT_DATABASE_URL", "sqlite:///./data/help-cat.db")
        self.storage_root = Path(storage_root or os.getenv("HELPCAT_STORAGE_ROOT", "./data/uploads"))
        self.max_image_bytes = int(os.getenv("HELPCAT_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))
        self.max_image_pixels = int(os.getenv("HELPCAT_MAX_IMAGE_PIXELS", str(24 * 1024 * 1024)))
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
