import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WelcomePageContractTests(unittest.TestCase):
    """The public welcome page is the promotion entry point: it must keep the
    paths a visitor is guided through, and it must not lose its ability to
    capture a contact when the API is unreachable."""

    def welcome_html(self):
        return (ROOT / "app" / "welcome" / "index.html").read_text(encoding="utf-8")

    def test_welcome_page_keeps_the_poster_pitch_and_actions(self):
        html = self.welcome_html()
        for marker in (
            "我在做一个", "帮流浪猫", "招同行人",
            "定点投喂", "伤病救助", "网站共建",
            "一起把这件事做起来",
            "查看管理员联系方式", "留个联系方式",
            "个人业余发起 · 有空时回复，不承诺随时响应",
            "www.helpcat.xyz",
        ):
            self.assertIn(marker, html)

    def test_welcome_page_wires_the_reveal_and_the_lead_form(self):
        html = self.welcome_html()
        for marker in (
            'id="enter-help-cat"',
            'id="reveal-contact"',
            'id="jump-to-form"',
            'id="contact-card"',
            'id="contact-wechat"',
            'id="contact-note"',
            'id="contact-qr"',
            'id="lead-form"',
            'id="lead-name"',
            'id="lead-contact-type"',
            'id="lead-contact"',
            'id="lead-message"',
            'id="lead-status"',
            'id="lead-submit"',
            'data-fallback-wechat=',
        ):
            self.assertIn(marker, html)

    def test_welcome_page_links_stay_correct_at_the_root_and_under_a_subpath(self):
        html = self.welcome_html()
        # `../rescue/` resolves to /rescue/ from both `/` and `/welcome/`.
        self.assertIn('href="../rescue/index.html"', html)
        self.assertIn("assets/help-cat-hero.webp", html)
        self.assertIn("assets/site-qr.png", html)
        for asset in ("help-cat-hero.webp", "site-qr.png"):
            self.assertTrue((ROOT / "app" / "welcome" / "assets" / asset).is_file(), asset)

    def test_lead_form_module_loads_before_the_dom_wiring(self):
        html = self.welcome_html()
        self.assertLess(html.index("lead-form.js?v="), html.index("welcome.js?v="))
        for asset in ("styles.css", "welcome.js", "lead-form.js"):
            self.assertTrue((ROOT / "app" / "welcome" / asset).is_file(), asset)

    def test_welcome_script_uses_only_public_api_routes(self):
        script = (ROOT / "app" / "welcome" / "welcome.js").read_text(encoding="utf-8")
        self.assertIn("/api/v1/public/contact", script)
        self.assertIn("/api/v1/public/messages", script)
        self.assertNotIn("/api/v1/admin/", script)
        # The reveal must survive an unreachable API.
        self.assertIn("operatorChannels(null, fallback)", script)

    def test_lead_form_module_is_shareable_with_the_runtime_test(self):
        source = (ROOT / "app" / "welcome" / "lead-form.js").read_text(encoding="utf-8")
        self.assertIn("module.exports = api", source)
        self.assertIn("root.HelpCatLeadForm = api", source)

    def test_welcome_page_has_no_duplicate_element_ids(self):
        html = self.welcome_html()
        ids = re.findall(r'\sid="([^"]+)"', html)
        self.assertEqual(sorted(ids), sorted(set(ids)), "duplicate ids: %s" % sorted({i for i in ids if ids.count(i) > 1}))


class AdminMessagePanelContractTests(unittest.TestCase):
    """The console must expose the leads the welcome page collects."""

    def test_admin_shell_has_a_message_section_and_filters(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'data-section="messages"',
            'data-admin-section="messages"',
            'id="messages"',
            'id="message-count"',
            'id="message-nav-badge"',
            'id="refresh-messages"',
            'id="load-more-admin-messages"',
            'id="message-panel-message"',
            'data-message-filter=""',
            'data-message-filter="NEW"',
            'data-message-filter="CONTACTED"',
            'data-message-filter="CLOSED"',
        ):
            self.assertIn(marker, html)

    def test_admin_script_loads_and_triages_leads(self):
        script = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        for marker in (
            "/api/v1/admin/messages",
            "renderMessages",
            "loadMessages",
            "actOnMessage",
            "setMessageFilter",
            "data-message-action",
            "messageFilter",
            "newMessageCount",
            'messages: "留言板"',
        ):
            self.assertIn(marker, script)

    def test_admin_styles_cover_the_message_surface(self):
        styles = (ROOT / "admin" / "styles.css").read_text(encoding="utf-8")
        for marker in (".message-dot", ".nav-badge", ".filter-chip", ".lead-item", ".lead-contact", ".message-symbol"):
            self.assertIn(marker, styles)


if __name__ == "__main__":
    unittest.main()
