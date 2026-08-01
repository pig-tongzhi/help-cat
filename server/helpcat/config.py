import os
from pathlib import Path


class Settings:
    def __init__(self, database_url=None, storage_root=None, fake_admin_openids=None):
        self.database_url = database_url or os.getenv("HELPCAT_DATABASE_URL", "sqlite:///./data/help-cat.db")
        self.storage_root = Path(storage_root or os.getenv("HELPCAT_STORAGE_ROOT", "./data/uploads"))
        self.max_image_bytes = int(os.getenv("HELPCAT_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))
        self.session_days = int(os.getenv("HELPCAT_SESSION_DAYS", "30"))
        self.fake_admin_openids = set(fake_admin_openids or filter(None, os.getenv("HELPCAT_FAKE_ADMIN_OPENIDS", "").split(",")))
        self.wechat_app_id = os.getenv("HELPCAT_WECHAT_APP_ID", "")
        self.wechat_app_secret = os.getenv("HELPCAT_WECHAT_APP_SECRET", "")
        self.allowed_origins = [item for item in os.getenv("HELPCAT_ALLOWED_ORIGINS", "").split(",") if item]
        self.admin_usernames = set(filter(None, os.getenv("HELPCAT_ADMIN_USERNAMES", "").split(",")))
