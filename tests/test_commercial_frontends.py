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
        script = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        self.assertIn('var H5_TOKEN_KEY = "help_cat_token"', script)
        self.assertIn('request("/api/v1/auth/logout", { method: "POST" })', script)
        self.assertIn("sessionStorage.removeItem(H5_TOKEN_KEY)", script)
        self.assertIn('byId("logout").addEventListener("click", logout)', script)


if __name__ == "__main__":
    unittest.main()
