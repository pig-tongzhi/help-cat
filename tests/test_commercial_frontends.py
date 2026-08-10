import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CommercialFrontendContractTests(unittest.TestCase):
    def test_mini_program_has_production_pages_and_no_demo_identity_switch(self):
        app_json = json.loads((ROOT / "miniapp" / "app.json").read_text(encoding="utf-8"))
        pages = " ".join(app_json["pages"])
        for page in ("pages/home/home", "pages/cats/new", "pages/submissions/submissions", "pages/tasks/tasks"):
            self.assertIn(page, pages)
        api = (ROOT / "miniapp" / "utils" / "api.js").read_text(encoding="utf-8")
        self.assertIn("/api/v1/auth/wechat-login", api)
        self.assertNotIn("help-cat-role", api)
        new_cat = (ROOT / "miniapp" / "pages" / "cats" / "new.js").read_text(encoding="utf-8")
        new_cat_wxml = (ROOT / "miniapp" / "pages" / "cats" / "new.wxml").read_text(encoding="utf-8")
        self.assertIn("wx.getLocation", new_cat)
        self.assertIn("获取当前位置", new_cat_wxml)

    def test_admin_console_has_governance_surfaces_and_api_calls(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        session_script = (ROOT / "admin" / "session.js").read_text(encoding="utf-8")
        for text in ("猫咪档案库", "小区管理", "公开", "隐藏", "归档", "审核"):
            self.assertIn(text, html)
        for route in ("/api/v1/cats", "/api/v1/communities", "/review", "/visibility", "/archive"):
            self.assertIn(route, script)
        for text in ("/api/v1/auth/login", "管理员登录", "账号或密码错误", "sessionStorage"):
            self.assertIn(text, script)
        for text in ("用户与权限", "唯一超级管理员", "设为管理员", "撤销管理员"):
            self.assertIn(text, html + script)
        for route in ("/api/v1/auth/me", "/api/v1/admin/users", "/role"):
            self.assertIn(route, script)
        self.assertIn('profile.role === "SUPER_ADMIN"', script)
        self.assertIn('byId("login-password").value = ""', script)
        self.assertNotIn("API Token", html)
        self.assertNotIn("localStorage.setItem(\"help-cat-demo-v2\"", script)

    def test_admin_logout_revokes_server_session_and_clears_shared_h5_token(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        session_script = (ROOT / "admin" / "session.js").read_text(encoding="utf-8")
        self.assertIn('var H5_TOKEN_KEY = "help_cat_token"', script)
        self.assertIn('request("/api/v1/auth/logout", { method: "POST" })', session_script)
        self.assertIn("sessionStorage.removeItem(H5_TOKEN_KEY)", script)
        self.assertIn('byId("logout").addEventListener("click", logout)', script)
        self.assertIn('window.HelpCatAdminSession.logout(request, clearSession, showLogin, state)', script)
        self.assertLess(html.index('session.js?v='), html.index('app.js?v='))

    def test_admin_brand_returns_home_and_linked_review_is_versioned_and_paged(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        brand_source = 'src="/help-cat/rescue/assets/brand/helpcat-77-mark.svg"'
        self.assertIn('class="side-brand" href="/help-cat/rescue/index.html#home"', html)
        self.assertIn('aria-label="返回帮帮小猫首页"', html)
        self.assertIn('title="返回帮帮小猫首页"', html)
        self.assertEqual(html.count(brand_source), 2)
        self.assertEqual(html.count('<img class="brand-mark"'), 2)
        self.assertNotIn('<span class="brand-mark"', html)
        self.assertNotIn("access_token=", html + script)
        for marker in (
            'data-community-action="approve"',
            'data-community-action="request_changes"',
            'data-community-action="merge"',
            'data-community-action="reject"',
            'data-linked-cat',
            'community_review_blocker',
            'id="load-more-admin-cats"',
            'id="load-more-admin-users"',
            'data-cat-reassign-target',
            'data-target-search',
            'linked_cat_count',
            'merged_into_name',
            'cat.community_name',
            'id="load-more-admin-communities"',
            'community-review.js?v=',
            'next_cursor',
            'limit=24',
        ):
            self.assertIn(marker, html + script)
        self.assertLess(html.index('session.js?v='), html.index('community-review.js?v='))
        self.assertLess(html.index('community-review.js?v='), html.index('app.js?v='))

    def test_admin_uses_premium_responsive_system_and_exact_motto(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "admin" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<footer class="brand-footer admin-footer"><small>安得广厦千万间，大庇天下小猫俱欢颜</small></footer>', html)
        self.assertEqual(html.count("安得广厦千万间，大庇天下小猫俱欢颜"), 1)
        for marker in ("#F5F5F7", "#1D1D1F", "clamp(", "min-height: 44px", "@media (prefers-reduced-motion: reduce)"):
            self.assertIn(marker, styles)
        for width in ("1024px", "820px", "430px", "390px", "360px"):
            self.assertIn(width, styles)

    def test_release_runbook_deploys_complete_rescue_tree_and_uses_one_release_root(self):
        runbook = (ROOT / "docs" / "wiki" / "部署回滚与运维.md").read_text(encoding="utf-8")
        changes = (ROOT / "docs" / "wiki" / "变更记录.md").read_text(encoding="utf-8")
        flow = (ROOT / "docs" / "wiki" / "核心业务流程.md").read_text(encoding="utf-8")
        for marker in (
            "发布整个 `app/rescue/` 目录",
            "story-77.js",
            "manifest.webmanifest",
            "assets/brand/",
            "assets/77/",
            "rescue.SHA256",
            "每个 HTML 引用资源",
            "HTTP 200",
        ):
            self.assertIn(marker, runbook)
        release_root = "/opt/help-cat/releases/<timestamp>"
        self.assertIn(release_root + "/scripts/help_cat_77_seed.py", changes)
        self.assertIn(release_root + "/rescue/assets/77/rescue-day.webp", changes)
        for marker in ("/api/v1/admin/cat-drafts/import", "PENDING_REVIEW", "HIDDEN", "人工"):
            self.assertIn(marker, changes + flow)


if __name__ == "__main__":
    unittest.main()
