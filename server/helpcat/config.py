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
        # 投稿自动预检：off（默认，全部进待审）/ shadow（只写审计，不改状态）/ on（通过即公开）
        self.auto_review = os.getenv("HELPCAT_AUTO_REVIEW", "off").strip().lower() or "off"
        self.session_days = int(os.getenv("HELPCAT_SESSION_DAYS", "30"))
        # 「记住这台设备」签发的长期会话。管理员在自己手机上想免登录就靠它，
        # 所以配套必须有设备列表 + 一键撤销（见 /api/v1/auth/sessions）。
        self.session_days_remember = int(os.getenv("HELPCAT_SESSION_DAYS_REMEMBER", "90"))
        self.fake_admin_openids = set(fake_admin_openids or filter(None, os.getenv("HELPCAT_FAKE_ADMIN_OPENIDS", "").split(",")))
        # 测试用的"假微信登录"（code 以 fake: 开头直接换 openid）。默认关闭：
        # 线上没配微信凭据时它等于一个万能登录后门，任何人都能用任意 openid 建号。
        self.allow_fake_wechat = os.getenv("HELPCAT_ALLOW_FAKE_WECHAT", "0").strip().lower() in {"1", "true", "yes", "on"}
        # API 文档（/docs、/redoc、/openapi.json）。默认关闭：线上没必要把全部接口和
        # 字段清单公开给所有人看；本地开发想看就设 HELPCAT_EXPOSE_API_DOCS=1。
        self.expose_api_docs = os.getenv("HELPCAT_EXPOSE_API_DOCS", "0").strip().lower() in {"1", "true", "yes", "on"}
        # 登录失败限速（同一账号 / 同一 IP）
        self.login_rate_limit_per_account = int(os.getenv("HELPCAT_LOGIN_LIMIT_PER_ACCOUNT", "10"))
        self.login_rate_limit_per_ip = int(os.getenv("HELPCAT_LOGIN_LIMIT_PER_IP", "30"))
        self.login_window_minutes = int(os.getenv("HELPCAT_LOGIN_WINDOW_MINUTES", "15"))
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
