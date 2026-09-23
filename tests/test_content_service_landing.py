import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app" / "content-service"


class ContentServiceLandingTest(unittest.TestCase):
    def test_landing_assets_and_offer_contract_exist(self):
        self.assertTrue((ROOT / "index.html").exists())
        self.assertTrue((ROOT / "styles.css").exists())
        self.assertTrue((ROOT / "app.js").exists())
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("3 条短视频内容包", html)
        self.assertIn("99 元", html)
        self.assertIn("提交需求", html)

    def test_landing_has_intake_form_and_no_guaranteed_results_claim(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="intake-form"', html)
        self.assertIn('id="contact"', html)
        self.assertIn("不承诺播放量", html)
        self.assertNotIn("保证爆款", html)

    def test_javascript_has_balanced_braces_and_no_external_dependency(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertEqual(script.count("{"), script.count("}"))
        self.assertNotIn("https://", script)


if __name__ == "__main__":
    unittest.main()
