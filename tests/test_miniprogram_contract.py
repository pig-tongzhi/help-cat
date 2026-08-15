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

    def test_app_secret_never_enters_client_bundle(self):
        source = "\n".join(
            path.read_text()
            for path in MINI.rglob("*")
            if path.is_file() and path.suffix in {".js", ".json", ".wxml", ".wxss"}
        )
        self.assertNotIn("app_secret", source.lower())
        self.assertNotIn("HELPCAT_WECHAT_APP_SECRET", source)


if __name__ == "__main__":
    unittest.main()
