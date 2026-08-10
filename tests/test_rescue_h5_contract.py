import json
import hashlib
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RescueH5ContractTests(unittest.TestCase):
    def test_77_public_media_is_sanitized_and_wired(self):
        asset_dir = ROOT / "app" / "rescue" / "assets" / "77"
        asset_names = (
            "hero-desktop.webp",
            "hero-mobile.webp",
            "rescue-day.webp",
            "grown-up.webp",
            "resting.webp",
        )
        for name in asset_names:
            path = asset_dir / name
            self.assertTrue(path.is_file(), f"{name} must exist")
            self.assertLess(path.stat().st_size, 450 * 1024, f"{name} must be below 450 KiB")
        self.assertNotEqual(
            hashlib.sha256((asset_dir / "hero-desktop.webp").read_bytes()).hexdigest(),
            hashlib.sha256((asset_dir / "hero-mobile.webp").read_bytes()).hexdigest(),
            "desktop and mobile heroes must use distinct responsive compositions",
        )

        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        for path in ("assets/77/hero-desktop.webp", "assets/77/hero-mobile.webp"):
            self.assertIn(path, html)
        self.assertIn(
            '<img src="assets/77/hero-desktop.webp" alt="77，一只白底黑斑的猫咪" width="960" height="720"',
            html,
        )

        story = (ROOT / "app" / "rescue" / "story-77.js").read_text(encoding="utf-8")
        for path in ("assets/77/rescue-day.webp", "assets/77/grown-up.webp", "assets/77/resting.webp"):
            self.assertIn(path, story)
        for alt in ("77 幼猫期的近照", "长大后的 77 正面近照", "77 安静休息的近照"):
            self.assertIn('alt: "' + alt + '"', story)
        self.assertIn("alt=\"' + escapeHtml(chapter.alt) + '\" width=\"", story)
        self.assertIn("index === 0 ? '' : ' loading=\"lazy\"'", story)

    def test_77_brand_assets_and_manifest_are_wired(self):
        page = (ROOT / "app/rescue/index.html").read_text()
        for marker in (
            '<meta name="theme-color" content="#F7F5F1">',
            'rel="icon" href="assets/brand/favicon.svg"',
            'rel="apple-touch-icon" href="assets/brand/apple-touch-icon.png"',
            'rel="manifest" href="manifest.webmanifest"',
            'class="brand-logo brand-logo-77"',
        ):
            self.assertIn(marker, page)
        svg = (ROOT / "app/rescue/assets/brand/helpcat-77-mark.svg").read_text()
        self.assertIn('viewBox="0 0 64 64"', svg)
        self.assertIn('aria-labelledby="helpcat-77-title"', svg)
        manifest = json.loads((ROOT / "app/rescue/manifest.webmanifest").read_text())
        self.assertEqual(manifest["name"], "帮帮小猫")
        self.assertEqual({icon["sizes"] for icon in manifest["icons"]}, {"192x192", "512x512"})

    def test_rescue_home_has_editorial_hero_and_story_entry(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            'class="editorial-hero"',
            '<h1 id="home-title">让每一只小猫，<br>都被认真看见</h1>',
            '<picture class="editorial-hero-visual">',
            'data-nav="story-77"',
            'id="metric-communities"',
            'id="home-cats"',
            'id="home-tasks"',
            "公开猫咪",
            "开放任务",
            "覆盖小区",
        ):
            self.assertIn(marker, html)
        self.assertIn(".editorial-hero", styles)
        self.assertNotIn("A HOME FOR EVERY CAT", html)
        self.assertNotIn('class="region-chip"', html)
        self.assertNotIn('class="hero-mark"', html)
        self.assertNotIn(".hero-mark", styles)

    def test_rescue_story_route_is_shareable_and_actionable(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        story = (ROOT / "app" / "rescue" / "story-77.js").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in ('id="story-77"', 'data-view="story-77"', 'story-77.js?v='):
            self.assertIn(marker, html)
        for marker in ('"story-77"', "window.addEventListener(\"hashchange\", syncRouteFromHash)", "window.history.pushState", "homeScrollY"):
            self.assertIn(marker, script)
        for marker in ("返回首页", 'data-story-action="cats"', 'data-story-action="create-cat"'):
            self.assertIn(marker, story)
        for selector in (".story-timeline", ".story-chapter:nth-child(even)", ".story-back"):
            self.assertIn(selector, styles)

    def test_rescue_metrics_use_deduplicated_public_collections(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            "function renderMetrics()",
            "uniqueCollectionCount(state.cats)",
            "uniqueCollectionCount(state.tasks)",
            "uniqueCollectionCount(state.communities)",
            'new Intl.NumberFormat("zh-CN")',
            "return String(value)",
            'byId("metric-communities")',
        ):
            self.assertIn(marker, script)
        self.assertGreaterEqual(script.count("renderMetrics();"), 2)

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
            "function normalizedRole(role)",
            "function isAdminRole(role)",
            "var value = normalizedRole(role)",
            'byId("admin-console-action").hidden = !admin',
            'sessionStorage.setItem("help_cat_admin_token", api.token())',
            'window.location.assign("/help-cat/admin/")',
            'role === "SUPER_ADMIN" ? "超级管理员"',
            '"超级管理员账号 · 新建档案将直接公开"',
        ):
            self.assertIn(marker, script)

    def test_role_aware_community_creation_entry(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="open-community-form"',
            'id="community-section-title"',
            'id="community-section-description"',
            'id="community-submit"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "function normalizedRole(role)",
            "function renderCommunityEntry()",
            'byId("open-community-form").addEventListener("click"',
            'isAdminRole(state.user && state.user.role)',
        ):
            self.assertIn(marker, script)

    def test_cat_flow_supports_inline_candidate_correction_and_bounded_pages(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'data-community-mode="existing"',
            'data-community-mode="new"',
            'aria-pressed="true"',
            'id="cat-community-candidate-name"',
            'id="cat-community-candidate-street"',
            'id="cat-community-candidate-note"',
            'id="load-more-cats"',
            'id="load-more-tasks"',
            'id="load-more-submissions"',
            'id="load-more-communities"',
            'community-form.js?v=',
        ):
            self.assertIn(marker, html)
        for marker in (
            "buildCatCommunityPayload",
            "buildCommunityEditPayload",
            'data-edit-community',
            'data-community-correction-form',
            'community_review_blocker',
            'next_cursor',
            'limit=24',
        ):
            self.assertIn(marker, script)
        self.assertLess(html.index('api.js?v='), html.index('community-form.js?v='))
        self.assertLess(html.index('community-form.js?v='), html.index('app.js?v='))

    def test_live_version_update_contract(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        version_script = (ROOT / "app" / "rescue" / "version.js").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            'data-app-version="20260811-77-editorial-r1"',
            'id="version-update"',
            'id="reload-version"',
        ):
            self.assertIn(marker, html)
        for marker in ("function checkForUpdate()", "window.HelpCatVersion.checkForUpdate"):
            self.assertIn(marker, script)
        for marker in (
            'fetchPage(path, { cache: "no-store" })',
            "if (!response.ok)",
            "if (match && match[1] !== current)",
            'CURRENT_VERSION = "20260811-77-editorial-r1"',
            "current: CURRENT_VERSION",
        ):
            self.assertIn(marker, version_script)
        self.assertIn('document.addEventListener("visibilitychange"', script)
        self.assertLess(html.index('version.js?v='), html.index('app.js?v='))
        self.assertIn(".version-update", styles)

    def test_rescue_app_maps_business_errors_and_blocks_duplicate_submit(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for text in ("daily_cat_limit_reached", "task_already_claimed", "invalid_credentials", "submitting", "uploadImage"):
            self.assertIn(text, script)
        for text in ('Idempotency-Key', 'catIdempotencyKey', 'crypto.randomUUID', 'prefers-reduced-motion'):
            self.assertIn(text, script)
        self.assertIn('cat.community_name', script)

    def test_rescue_assets_are_versioned_in_dependency_order(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        version = "20260811-77-editorial-r1"
        for asset in ("styles.css", "api.js", "community-form.js", "version.js", "story-77.js", "app.js"):
            self.assertIn(f'{asset}?v={version}', html)
        api_index = html.index(f'api.js?v={version}')
        version_index = html.index(f'version.js?v={version}')
        app_index = html.index(f'app.js?v={version}')
        self.assertLess(api_index, version_index)
        self.assertLess(version_index, app_index)

    def test_77_story_has_responsive_accessible_mobile_contract(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        story = (ROOT / "app" / "rescue" / "story-77.js").read_text(encoding="utf-8")

        for marker in (
            "env(safe-area-inset-bottom)",
            "@media (prefers-reduced-motion: reduce)",
            ".story-back:focus-visible",
            "@media (max-width: 720px)",
            ".story-chapter { grid-template-columns: 1fr;",
            "@media (min-width: 721px) and (max-width: 1024px)",
            ".cat-grid { grid-template-columns: repeat(3, minmax(0, 1fr));",
            ".compact-grid { grid-template-columns: repeat(2, minmax(0, 1fr));",
        ):
            self.assertIn(marker, styles)

        for container in ("app-shell", "story-view", "story-page"):
            self.assertNotRegex(styles, rf"\\.{container}[^{{]*\\{{[^}}]*100vw")
        self.assertNotIn(".cat-grid,.compact-grid { grid-template-columns: 1fr; }", styles)
        self.assertGreater(
            styles.index("@media (min-width: 721px) and (max-width: 1024px)"),
            styles.rindex("@media (max-width: 820px)"),
            "tablet archive rules must override the broader 820px fallback",
        )

        self.assertIn('<button class="story-back" type="button"', story)
        self.assertIn('<button class="button primary" type="button" data-story-action="cats">', story)
        self.assertIn('<button class="button secondary" type="button" data-story-action="create-cat">', story)
        self.assertIn('story-77.js?v=20260811-77-editorial-r1', html)

    def test_rescue_uses_premium_tokens_responsive_type_and_exact_motto(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<footer class="brand-footer"><small>安得广厦千万间，大庇天下小猫俱欢颜</small></footer>', html)
        self.assertEqual(html.count("安得广厦千万间，大庇天下小猫俱欢颜"), 1)
        for marker in ("#F5F5F7", "#1D1D1F", "clamp(", "min-height: 44px", "@media (prefers-reduced-motion: reduce)"):
            self.assertIn(marker, styles)
        for width in ("1024px", "820px", "430px", "390px", "360px"):
            self.assertIn(width, styles)


if __name__ == "__main__":
    unittest.main()
