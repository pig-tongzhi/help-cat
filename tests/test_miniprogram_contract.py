import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


class MiniProgramContractTests(unittest.TestCase):
    def test_native_project_exposes_core_tabs(self):
        config = json.loads((MINI / "app.json").read_text())
        self.assertEqual(config["pages"][0], "pages/home/index")
        self.assertEqual(
            [item["pagePath"] for item in config["tabBar"]["list"]],
            ["pages/home/index", "pages/cats/index", "pages/tasks/index", "pages/profile/index"],
        )

    def test_api_uses_https_domain_and_wechat_login(self):
        source = (MINI / "utils/api.js").read_text()
        self.assertIn('https://helpcat.xyz/api/v1', source)
        self.assertNotIn("175.178.41.19", source)
        self.assertIn('/auth/wechat-login', source)
        self.assertIn('Authorization', source)

    def test_core_pages_have_loading_error_and_empty_states(self):
        for page in ("home", "cats", "tasks", "profile"):
            js = (MINI / "pages" / page / "index.js").read_text()
            wxml = (MINI / "pages" / page / "index.wxml").read_text()
            self.assertIn("loading", js + wxml, page)
            self.assertIn("error", js + wxml, page)
            self.assertIn("empty", js + wxml, page)

    def test_home_enables_pull_down_refresh(self):
        config = json.loads((MINI / "pages/home/index.json").read_text())
        self.assertTrue(config.get("enablePullDownRefresh"), "首页声明了 onPullDownRefresh，必须开启下拉刷新")

    def test_cat_list_honours_the_profile_deep_link(self):
        source = (MINI / "pages/cats/index.js").read_text()
        self.assertIn("onLoad(options)", source)
        self.assertIn("options.profile", source)
        self.assertIn("/public/profiles/", source)

    def test_enums_are_never_shown_raw_to_users(self):
        cats_js = (MINI / "pages/cats/index.js").read_text()
        cats_wxml = (MINI / "pages/cats/index.wxml").read_text()
        profile_js = (MINI / "pages/profile/index.js").read_text()
        profile_wxml = (MINI / "pages/profile/index.wxml").read_text()
        self.assertIn("HEALTH_LABELS", cats_js)
        self.assertIn("health_label", cats_wxml)
        self.assertNotIn("{{item.health_status}}", cats_wxml)
        self.assertIn("ROLE_LABELS", profile_js)
        self.assertIn("role_label", profile_wxml)
        self.assertNotIn("{{user.role}}", profile_wxml)

    def test_claiming_a_task_requires_a_session_first(self):
        source = (MINI / "pages/tasks/index.js").read_text()
        gate = source[source.index("claim(event)"):]
        self.assertIn("globalData.token", gate)
        self.assertLess(gate.index("globalData.token"), gate.index("api.request("), "登录检查必须在请求之前")
        self.assertIn("task_already_claimed", gate)

    def test_app_secret_never_enters_client_bundle(self):
        source = "\n".join(
            path.read_text()
            for path in MINI.rglob("*")
            if path.is_file() and path.suffix in {".js", ".json", ".wxml", ".wxss"}
        )
        self.assertNotIn("app_secret", source.lower())
        self.assertNotIn("HELPCAT_WECHAT_APP_SECRET", source)

    def test_public_photo_lists_use_thumbnails_lazy_loading_and_error_fallback(self):
        cats_js = (MINI / "pages/cats/index.js").read_text()
        cats_wxml = (MINI / "pages/cats/index.wxml").read_text()
        home_js = (MINI / "pages/home/index.js").read_text()
        home_wxml = (MINI / "pages/home/index.wxml").read_text()
        for source in (cats_js, home_js):
            self.assertIn("photo_failed:false", source)
            self.assertIn("onPhotoError", source)
            self.assertIn("api.mediaUrl", source)
        for source in (cats_wxml, home_wxml):
            self.assertIn('lazy-load="{{true}}"', source)
            self.assertIn('binderror="onPhotoError"', source)
            self.assertIn("wx:else", source)


if __name__ == "__main__":
    unittest.main()
