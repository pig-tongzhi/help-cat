import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RescueH5ContractTests(unittest.TestCase):
    def test_rescue_page_contains_enterprise_product_copy_and_privacy(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        for text in ("帮帮小猫", "Help Cat", "银湖街道", "猫咪档案", "救助任务", "我的", "精确位置不会公开"):
            self.assertIn(text, html)
        for text in ("演示身份", "重置演示", "体验版"):
            self.assertNotIn(text, html)

    def test_rescue_page_has_enterprise_mobile_shell(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in ('data-view="home"', 'data-view="cats"', 'data-view="tasks"', 'data-view="profile"', 'id="auth-sheet"', 'id="cat-sheet"'):
            self.assertIn(marker, html)
        self.assertIn("position: fixed", styles)
        self.assertIn("min-height: 44px", styles)

    def test_rescue_client_uses_real_api_and_session_token(self):
        path = ROOT / "app" / "rescue" / "api.js"
        self.assertTrue(path.is_file(), "api.js must exist")
        script = path.read_text(encoding="utf-8")
        self.assertIn('API_BASE = "/help-cat-api"', script)
        self.assertIn('sessionStorage.getItem("help_cat_token")', script)
        self.assertIn('/api/v1/auth/me', script)
        self.assertNotIn('help-cat-demo-v2', script)

    def test_rescue_app_has_real_auth_data_and_location_fallback(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for text in ("loadPublicData", "requireLogin", "/api/v1/communities", "/api/v1/cats", "/api/v1/tasks", "/api/v1/me/submissions", "navigator.geolocation", "location-fallback"):
            self.assertIn(text, script)
        self.assertNotIn("help-cat-demo-v2", script)
        self.assertNotIn("role-select", script)

    def test_rescue_styles_define_enterprise_visual_system(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for text in ("--brand", "--surface", "--radius-lg", ".bottom-nav", ".sheet", ".cat-card", ".task-card", "@media"):
            self.assertIn(text, styles)

    def test_cat_card_contract_has_permanent_placeholder_and_broken_image_fallback(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for text in ("healthTone", "cat-placeholder", "data-cat-photo", "image-failed", 'addEventListener("error"', "target.hidden = true"):
            self.assertIn(text, script)
        for legacy_value in ('"良好": "healthy"', '"需要观察": "attention"', '"需要帮助": "attention"'):
            self.assertIn(legacy_value, script)
        self.assertLess(script.index("cat-placeholder"), script.index("data-cat-photo"))

    def test_cat_card_styles_match_markup_and_adapt_desktop_tablet_mobile(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for selector in (".cat-card-body", ".cat-title", ".cat-community", ".cat-placeholder", ".health-badge", ".image-failed", ".task-priority", ".task-copy", ".submission-type", ".review-status"):
            self.assertIn(selector, styles)
        for behavior in ("reviewTone", 'APPROVED: "approved"', 'PENDING_REVIEW: "pending"', 'REJECTED: "rejected"'):
            self.assertIn(behavior, script)
        for selector in (".review-status.approved", ".review-status.pending", ".review-status.rejected"):
            self.assertIn(selector, styles)
        for behavior in ("-webkit-line-clamp", "@media (max-width: 1024px)", "@media (max-width: 720px)", "grid-template-columns: minmax(118px, 34%) 1fr"):
            self.assertIn(behavior, styles)

    def test_rescue_page_contains_auth_and_three_step_cat_flow(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        for text in ("登录", "注册", "cat-community", "cat-photo-file", 'accept="image/*"', "use-current-location", "location-fallback", "下一步", "上一步"):
            self.assertIn(text, html)
        self.assertNotIn('capture=', html)
        self.assertNotIn("admin-tools", html)

    def test_admin_roles_get_same_session_management_entry(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="admin-console-action"', html)
        self.assertIn('id="admin-console-action" type="button" hidden', html)
        for marker in (
            "function isAdminRole(role)",
            'role === "ADMIN" || role === "SUPER_ADMIN"',
            'byId("admin-console-action").hidden = !admin',
            'sessionStorage.setItem("help_cat_admin_token", api.token())',
            'window.location.assign("/help-cat/admin/")',
            'role === "SUPER_ADMIN" ? "超级管理员"',
            '"超级管理员账号 · 新建档案将直接公开"',
        ):
            self.assertIn(marker, script)

    def test_rescue_app_maps_business_errors_and_blocks_duplicate_submit(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for text in ("daily_cat_limit_reached", "task_already_claimed", "invalid_credentials", "submitting", "uploadImage"):
            self.assertIn(text, script)

    def test_rescue_assets_are_versioned_in_dependency_order(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        self.assertIn('styles.css?v=20260802-mobile-admin', html)
        api_index = html.index('api.js?v=20260802-mobile-admin')
        app_index = html.index('app.js?v=20260802-mobile-admin')
        self.assertLess(api_index, app_index)


if __name__ == "__main__":
    unittest.main()
