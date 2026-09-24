import json
import hashlib
import pathlib
import re
import unittest

from PIL import Image


ROOT = pathlib.Path(__file__).resolve().parents[1]


def last_rule(css, selector):
    """取某选择器在样式表里**最后**一条规则的主题 —— 级联里后写的生效。
    直接 re.search 拿第一条会读到被覆盖的旧规则（这个坑踩过不止一次）。"""
    # 选择器必须是"整条选择器"：`.has-motion .hero-atmosphere` 里的那一段不算
    # （否则会读到减少动效块里的 transform: none，而不是基础规则）
    pattern = r"(?:^|[},])\s*" + re.escape(selector) + r"\s*\{(?P<body>[^}]*)\}"
    matches = list(re.finditer(pattern, css, re.M))
    assert matches, selector + " 缺少规则"
    return matches[-1].group("body")


def all_rules(css, selector):
    """某选择器的**所有**规则主题拼起来。

    用在"这条属性有没有被设过"上：后面的规则只会覆盖它自己声明的属性，
    所以基础规则里写的 max-width / background 在没有被重复声明时依然生效。
    （要判断"某个属性最终是什么"，才该用 last_rule。）"""
    pattern = r"(?:^|[},])\s*" + re.escape(selector) + r"\s*\{(?P<body>[^}]*)\}"
    return "\n".join(match.group("body") for match in re.finditer(pattern, css, re.M))


def without_css_comments(css):
    r"""去掉 CSS 注释再做规则扫描。

    这两条 hero 契约测试用 `[^{]*\{` 抓"某选择器对应的规则"，而注释里只要提到
    一次选择器名，`[^{]*` 就会一路吞到后面某条规则的 `{`，于是把那条规则的
    background 当成这条选择器的 —— 写注释解释约束反而会让测试失败。
    所以先把注释剥掉：注释是给人看的，不该参与契约判定。
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


class RescueH5ContractTests(unittest.TestCase):
    def test_77_public_media_is_sanitized_and_wired(self):
        asset_dir = ROOT / "app" / "rescue" / "assets" / "77"
        asset_names = (
            "cat-cutout.webp",
            "rescue-day.webp",
            "grown-up.webp",
            "portrait.webp",
        )
        for name in asset_names:
            path = asset_dir / name
            self.assertTrue(path.is_file(), f"{name} must exist")
            self.assertLess(path.stat().st_size, 450 * 1024, f"{name} must be below 450 KiB")

        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        self.assertIn("assets/77/cat-cutout.webp", html)
        self.assertIn(
            '<img src="assets/77/cat-cutout.webp?v=20260923-product-r18" alt="77，一只白底黑斑的猫咪" width="760" height="851"',
            html,
        )

        story = (ROOT / "app" / "rescue" / "story-77.js").read_text(encoding="utf-8")
        for path in ("assets/77/rescue-day.webp", "assets/77/grown-up.webp", "assets/77/portrait.webp"):
            self.assertIn(path, story)
        for alt in ("77 幼猫期的近照", "长大后的 77 正面近照", "77 正面坐着的近照"):
            self.assertIn('alt: "' + alt + '"', story)
        # 故事图以前没有版本号：换图之后老用户会被 7 天图片缓存顶住，还是看到旧图。
        self.assertIn("versioned(chapter.image)", story)
        self.assertIn("window.HelpCatVersion", story)
        self.assertIn("alt=\"' + escapeHtml(chapter.alt) + '\" width=\"", story)
        self.assertIn("index === 0 ? '' : ' loading=\"lazy\"'", story)

    def test_story_media_is_complete_and_retryable(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        story = (ROOT / "app" / "rescue" / "story-77.js").read_text(encoding="utf-8")
        self.assertIn('data-story-image', story)
        # 一次网络抖动不该让照片永久消失：先自动重试，再退到手动按钮。
        self.assertIn("if (attempts === 0)", story)
        self.assertIn('addEventListener("load"', story)
        self.assertIn('data-story-retry', story)
        self.assertIn('data-story-source', story)
        self.assertIn('.story-visual.has-image img', styles)
        image_rule = re.search(r"\.story-visual\.has-image\s+img\s*\{(?P<body>[^}]*)\}", styles)
        self.assertIsNotNone(image_rule)
        self.assertIn("object-fit: contain", image_rule.group("body"))
        self.assertNotIn("object-fit: cover", image_rule.group("body"))

    def test_77_brand_assets_and_manifest_are_wired(self):
        page = (ROOT / "app/rescue/index.html").read_text()
        for marker in (
            '<meta name="theme-color" content="#F7F5F1">',
            'rel="icon" href="assets/brand/favicon.svg?v=20260923-product-r18"',
            'rel="apple-touch-icon" href="assets/brand/apple-touch-icon.png?v=20260923-product-r18"',
            'rel="manifest" href="manifest.webmanifest?v=20260923-product-r18"',
            'class="brand-logo brand-logo-77"',
        ):
            self.assertIn(marker, page)
        svg = (ROOT / "app/rescue/assets/brand/helpcat-77-mark.svg").read_text()
        self.assertIn('viewBox="0 0 64 64"', svg)
        self.assertIn('aria-labelledby="helpcat-77-title"', svg)
        manifest = json.loads((ROOT / "app/rescue/manifest.webmanifest").read_text())
        self.assertEqual(manifest["name"], "帮帮小猫")
        self.assertEqual({icon["sizes"] for icon in manifest["icons"]}, {"192x192", "512x512"})

    def test_brand_uses_one_77_master_across_all_surfaces(self):
        page = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "app" / "rescue" / "manifest.webmanifest").read_text(encoding="utf-8"))
        version = "20260923-product-r18"
        master = "assets/brand/helpcat-77-mark.svg?v=" + version

        self.assertRegex(
            page,
            r'\.brand-logo\.brand-logo-77\s*\{[^}]*url\(["\']' + re.escape(master) + r'["\']\)',
        )
        self.assertIn('rel="icon" href="assets/brand/favicon.svg?v=' + version + '"', page)
        self.assertIn('rel="apple-touch-icon" href="assets/brand/apple-touch-icon.png?v=' + version + '"', page)
        self.assertIn('rel="manifest" href="manifest.webmanifest?v=' + version + '"', page)
        self.assertEqual(
            (ROOT / "app" / "rescue" / "assets" / "brand" / "favicon.svg").read_bytes(),
            (ROOT / "app" / "rescue" / "assets" / "brand" / "helpcat-77-mark.svg").read_bytes(),
            "favicon must reuse the one 77 SVG master rather than a second drawing",
        )
        self.assertEqual(
            {icon["src"] for icon in manifest["icons"]},
            {
                "assets/brand/icon-192.png?v=" + version,
                "assets/brand/icon-512.png?v=" + version,
            },
        )
        svg = (ROOT / "app" / "rescue" / "assets" / "brand" / "helpcat-77-mark.svg").read_text(encoding="utf-8")
        for feature in (
            '<path fill="#FFFFFF" d="M14.2 23.5 16.5 8.5l11.7 10q3.8-1.3 7.6 0L47.8 8l2.4 15.5q2.5 5.1 1 12.2C50.1 46.9 43.2 54 32.2 54S14.3 46.9 13.1 35.7q-.8-7 1.1-12.2Z"/>',
            '<path fill="#171717" d="m36.4 18.8 11.2-9.2 2 14.7c1.4 2.2 1.2 5.4-.4 7.8-1.8 2.8-5.2 4.3-8.4 3.4-3.7-1-6.2-4.3-6.3-8.3-.1-3 .5-5.6 1.9-8.4Z"/>',
            '<ellipse cx="24.7" cy="29.7" rx="1.35" ry="2.15" fill="#171717" stroke="none"/>',
            '<ellipse cx="41.3" cy="29.4" rx="1.65" ry="2.3" fill="#FFFFFF" stroke="none"/>',
            '<ellipse cx="41.3" cy="29.5" rx=".62" ry="1.2" fill="#171717" stroke="none"/>',
            '<path fill="#D99386" stroke="none" d="m30.7 37.3 1.3 1.25 1.3-1.25Z"/>',
        ):
            self.assertIn(feature, svg)
        self.assertNotIn('d="M12 26c0-7 8-11 20-11s20 4 20 11', svg)

    def test_hero_uses_one_continuous_warm_backdrop(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        marker = "/* Brand hero final cascade: keep last. */"
        self.assertEqual(styles.count(marker), 1, "the final hero cascade must have one explicit anchor")
        _, final_cascade = styles.split(marker, 1)
        final_cascade = without_css_comments(final_cascade)
        self.assertTrue(final_cascade.strip(), "the final hero cascade must contain effective rules")
        self.assertRegex(final_cascade, r":root\s*\{[^}]*--hero-backdrop:\s*#F5F1EB")
        for selector in (
            ".reference-hero",
            ".reference-hero .editorial-hero-copy",
            ".reference-hero .editorial-hero-visual",
        ):
            self.assertRegex(
                final_cascade,
                r"(?s)(?:^|})[^{}]*" + re.escape(selector) + r"[^{}]*\{[^{}]*background:\s*var\(--hero-backdrop\)",
                selector + " must use the final shared hero backdrop token",
            )
        for rule in re.findall(r"(?:\.reference-hero|\.editorial-hero-copy|\.editorial-hero-visual)[^{]*\{[^}]*\}", final_cascade):
            for value in re.findall(r"border(?:-left)?:\s*([^;}]+)", rule):
                self.assertEqual(value.strip(), "0")
            for value in re.findall(r"background:\s*([^;}]+)", rule):
                self.assertIn(value.strip(), ("var(--hero-backdrop)", "transparent"))

    def test_mobile_hero_keeps_77_visible_above_shared_backdrop(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        marker = "/* Brand hero final cascade: keep last. */"
        _, final_cascade = styles.split(marker, 1)
        final_cascade = without_css_comments(final_cascade)
        mobile = re.search(r"@media\s*\(max-width:\s*720px\)\s*\{(?P<body>.*)\}\s*$", final_cascade, re.S)
        self.assertIsNotNone(mobile)
        mobile_css = mobile.group("body")
        copy_rule = re.search(r"\.reference-hero\s+\.editorial-hero-copy\s*\{(?P<body>[^}]*)\}", mobile_css)
        visual_rule = re.search(r"\.reference-hero\s+\.editorial-hero-visual\s*\{(?P<body>[^}]*)\}", mobile_css)
        image_rule = re.search(r"\.reference-hero\s+\.editorial-hero-visual\s+img\s*\{(?P<body>[^}]*)\}", mobile_css)
        self.assertIsNotNone(copy_rule)
        self.assertIsNotNone(visual_rule)
        self.assertIsNotNone(image_rule)
        self.assertNotIn("background: var(--hero-backdrop)", copy_rule.group("body"))
        self.assertIn("background: transparent", copy_rule.group("body"))
        self.assertIn("pointer-events: none", copy_rule.group("body"))
        self.assertIn("object-fit: contain", image_rule.group("body"))
        self.assertNotIn("object-fit: cover", image_rule.group("body"))
        self.assertIn("width: 100%", image_rule.group("body"))
        self.assertIn("height: 100%", image_rule.group("body"))
        # 取景从 right bottom 改为 center bottom（满宽出血后右对齐会让猫贴死右边缘）；
        # 契约真正要的是 contain —— 77 完整可见、不裁切，这条没变。
        self.assertRegex(image_rule.group("body"), r"object-position:\s*center\s+bottom")

    def test_hero_cat_is_a_cutout_with_no_rectangle(self):
        """首屏的猫必须是抠像（带 alpha）：四边若有一圈不透明像素，
        就等于又把照片矩形贴回草坪上了。同时头顶要留白、脸要完全不透明。"""
        image = Image.open(ROOT / "app" / "rescue" / "assets" / "77" / "cat-cutout.webp")
        self.assertEqual("RGBA", image.mode, "抠像必须带 alpha 通道")
        alpha = image.getchannel("A")
        width, height = image.size
        ring = []
        for x in range(width):
            ring += [alpha.getpixel((x, 0)), alpha.getpixel((x, height - 1))]
        for y in range(height):
            ring += [alpha.getpixel((0, y)), alpha.getpixel((width - 1, y))]
        opaque = sum(1 for value in ring if value > 12)
        self.assertLess(opaque / len(ring), 0.02, "四边必须基本透明，否则就是没抠干净")

        bbox = alpha.point(lambda value: 255 if value > 40 else 0).getbbox()
        self.assertIsNotNone(bbox)
        left, top, right, bottom = bbox
        self.assertGreater(top, 12, "头顶要留白，耳朵不能被画布切掉")
        self.assertGreater(left, 4)
        self.assertGreater(width - right, 4)
        self.assertGreater((right - left) / width, 0.45, "主体占比太小会显得空")
        # 半透明的猫看着像幽灵：脸中心必须完全不透明
        self.assertEqual(255, alpha.getpixel((width // 2, int(height * 0.42))))

    def test_home_hero_is_a_meadow_stage(self):
        """草坪素材存在、被 CSS 引用，且近景草必须盖在猫前面（层级更高）。"""
        scenery = ROOT / "app" / "rescue" / "assets" / "scenery"
        for name in ("meadow-far.svg", "meadow-near.svg"):
            path = scenery / name
            self.assertTrue(path.is_file(), name + " 必须存在")
            self.assertLess(path.stat().st_size, 300 * 1024, name + " 不该是巨无霸")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('url("assets/scenery/meadow-far.svg")', styles)
        self.assertIn('url("assets/scenery/meadow-near.svg")', styles)
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="hero-meadow-front" aria-hidden="true"', html)
        self.assertIn('class="hero-atmosphere" aria-hidden="true"', html)
        # 近景草要比照片列高一层，否则草跑到猫后面，"站在草里"就没了
        self.assertIn("z-index: 3", all_rules(styles, ".hero-meadow-front"))

    def test_hero_is_a_clean_product_page_stage(self):
        """首屏走苹果产品页那套：近白底 + 巨大无衬线标题 + 一个强调色。
        背景里除了渐变和一层几乎看不见的暖光，不允许再有点阵/同心弧/彩色柔光。"""
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        atmosphere = all_rules(styles, ".hero-atmosphere")
        self.assertIn('url("assets/scenery/meadow-far.svg")', atmosphere, "首屏底色是草坪")
        self.assertNotIn("repeating-radial-gradient", styles, "同心弧已经删掉了")
        self.assertNotIn("background-image: radial-gradient(rgba(23, 23, 23", styles, "点阵已经删掉了")
        # 标题换成系统无衬线（苹果页面是 SF / PingFang），并且不能被旧宽度上限折成碎片
        h1 = all_rules(styles, ".reference-hero h1")
        self.assertIn('"PingFang SC"', styles)
        self.assertIn("max-width: none", h1)
        self.assertIn("letter-spacing: -.04em", h1)
        self.assertNotIn("Georgia", h1, "首屏标题不该再用衬线体")

    def test_hero_cat_is_never_cropped(self):
        """猫是抠像：任何宽度下都必须 contain。裁掉耳朵比留白糟得多，
        而且抠像一旦被 cover 裁切，草坪上就只剩半个猫头。"""
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        rules = all_rules(styles, ".reference-hero .editorial-hero-visual img")
        self.assertIn("object-fit: contain", rules)
        self.assertNotIn("object-fit: cover", rules)

    def test_hero_footnote_carries_the_77_facts(self):
        """首屏那行脚注是 77 故事的既有事实（初见时间 / 名字由来），不允许另编一套。
        它必须是文案块的直接子元素，才能跟着 nth-child 的分层入场一起落位。"""
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        story = (ROOT / "app" / "rescue" / "story-77.js").read_text(encoding="utf-8")
        for fact in ("2025 年 6 月 2 日", "农历五月初七"):
            self.assertIn(fact, html)
            self.assertIn(fact, story, fact + " 必须能在 77 故事里找到出处")
        copy_start = html.index('class="product-hero-copy editorial-hero-copy"')
        copy_end = html.index('<picture class="editorial-hero-visual">')
        self.assertIn("hero-footnote", html[copy_start:copy_end], "脚注要在文案块内（跟着分层入场）")
        self.assertGreater(html.index("hero-footnote"), html.index("editorial-hero-actions"))
        # 首屏只保留两个装饰层，且都对读屏器隐身
        self.assertEqual(2, len(re.findall(r'class="hero-(?:atmosphere|meadow-front)" aria-hidden="true"', html)))

    def test_data_band_stays_warm_and_light(self):
        """数据带保持浅色暖调 —— 深色那版被否了（"黑色有点难看"）。
        这条测试的作用就是别再把它做成深色。"""
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        band = all_rules(styles, ".impact-band")
        self.assertIn("linear-gradient(160deg, #FFFFFF", band, "数据带要回到原来那条暖色渐变")
        self.assertNotIn("#0B0B0C", styles, "深色数据带的覆盖必须清干净")
        self.assertNotIn("color: #FFFFFF", all_rules(styles, ".impact-band .metric-card strong"))

    def test_rescue_home_has_editorial_hero_and_story_entry(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            'class="reference-hero editorial-hero"',
            '<h1 id="home-title">让每一只小猫，<br>都被认真看见</h1>',
            '<picture class="editorial-hero-visual">',
            'data-nav="story-77"',
            'id="metric-rescued"',
            'id="metric-adopted"',
            'id="metric-medical"',
            'id="metric-supporters"',
            'id="home-cats"',
            'id="home-tasks"',
            "已救助",
            "找到新家",
            "医疗救助",
            "爱心支持",
        ):
            self.assertIn(marker, html)
        self.assertIn(".editorial-hero", styles)
        self.assertNotIn("A HOME FOR EVERY CAT", html)
        self.assertNotIn('class="region-chip"', html)
        self.assertNotIn('class="hero-mark"', html)
        self.assertNotIn(".hero-mark", styles)

    def test_home_matches_approved_editorial_layout_contract(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            'class="desktop-nav"',
            'class="mobile-menu-button"',
            'class="editorial-metric-icon',
            'class="reference-content-grid home-editorial-grid"',
            '<h2>猫咪档案</h2>',
            '<h2>救助任务</h2>',
            'class="metric-card"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)",
            "grid-template-columns: minmax(0, 3fr) minmax(220px, 1fr)",
            "object-fit: cover",
            ".desktop-nav",
            ".mobile-menu-button",
        ):
            self.assertIn(marker, styles)
        self.assertNotIn("background: var(--editorial-ink)", styles)
        self.assertIn(".editorial-hero:before { content: none; }", styles)

    def test_home_matches_confirmed_reference_content_and_responsive_navigation(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            'class="reference-hero editorial-hero"', 'class="impact-strip metric-grid"',
            'class="reference-content-grid home-editorial-grid"',
            'id="metric-rescued"', 'id="metric-adopted"', 'id="metric-medical"',
            'id="metric-supporters"', "已救助", "找到新家", "医疗救助", "爱心支持",
            '<span>首页</span>', '<span>投喂</span>', '<span>救助</span>',
            '<span>猫咪</span>', '<span>我的</span>',
        ):
            self.assertIn(marker, html)
        for marker in (
            '{ key: "rescued", label: "已救助" }',
            '{ key: "adopted", label: "找到新家" }',
            '{ key: "medical", label: "医疗救助" }',
            '{ key: "supporters", label: "爱心支持" }',
            '["rescued", "adopted", "medical", "supporters"]',
            "catsForDisplay(state.cats)", "state.tasks.slice(0, 1)",
        ):
            self.assertIn(marker, script)
        self.assertIn("@media (min-width: 721px)", styles)
        self.assertIn(".bottom-nav { display: none; }", styles)
        self.assertIn("padding-bottom: calc(78px + env(safe-area-inset-bottom))", styles)

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

    def test_rescue_metrics_use_independent_public_endpoint_and_explicit_error_state(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'data-metric-state="loading"',
            "function renderMetrics()",
            "function loadPublicMetrics()",
            'api.request("/api/v1/public/metrics")',
            'state.metrics.status = "ready"',
            'state.metrics.status = "error"',
            'amount === 0 ? "正在积累" : formatMetric(amount)',
            'value.setAttribute("aria-label", definition.label + "暂时无法获取")',
            'new Intl.NumberFormat("zh-CN")',
            "return String(value)",
            'key: "supporters"',
        ):
            self.assertIn(marker, html + script)
        render_metrics = script[script.index("function renderMetrics()"):script.index("function checkForUpdate()")]
        for collection in ("state.cats", "state.tasks", "state.communities"):
            self.assertNotIn(collection, render_metrics)
        search_metrics = script[script.index("function searchCatsFromServer()"):script.index("function scheduleCatSearch()")]
        self.assertNotIn("renderMetrics", search_metrics)

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
        for text in ("healthTone", "cat-placeholder", "data-cat-photo", "image-failed", 'addEventListener("error"', "target.hidden = true", "variant=thumb", "data-original-src", "photoRetry"):
            self.assertIn(text, script)
        for legacy_value in ('"良好": "healthy"', '"需要观察": "attention"', '"需要帮助": "attention"'):
            self.assertIn(legacy_value, script)
        self.assertLess(script.index("cat-placeholder"), script.index("data-cat-photo"))

    def test_list_cat_images_use_lazy_async_decoding_and_one_original_fallback(self):
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        self.assertIn('width="640" height="480" loading="lazy" decoding="async"', script)
        self.assertIn('data-original-src="', script)
        self.assertIn('target.dataset.photoRetry !== "original"', script)
        self.assertIn('media.classList.add("image-failed")', script)

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
            'data-app-version="20260923-product-r18"',
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
            'CURRENT_VERSION = "20260923-product-r18"',
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
        version = "20260923-product-r18"
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
        self.assertIn('story-77.js?v=20260923-product-r18', html)

    def test_primary_and_update_actions_meet_77_accessibility_contract(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")

        final_tokens = styles.rsplit(":root {", 1)[1]
        self.assertIn("--brand: #D9683A;", final_tokens)
        for marker in (
            ".button.primary { background: var(--brand); color: #171717;",
            ".button.primary:hover { background: var(--brand);",
            ".floating-action { position: fixed; right: max(20px, calc((100vw - 1180px) / 2 + 24px)); bottom: 84px; z-index: 18; display: none; align-items: center; gap: 7px; min-height: 48px; padding: 10px 15px; border: 0; border-radius: 999px; background: var(--brand); color: #171717;",
            ".version-update button { flex: 0 0 auto; min-width: 44px; min-height: 44px;",
            ".version-update button:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }",
        ):
            self.assertIn(marker, styles)

    def test_rescue_uses_premium_tokens_responsive_type_and_exact_motto(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<footer class="brand-footer"><small>安得广厦千万间，大庇天下小猫俱欢颜</small></footer>', html)
        self.assertEqual(html.count("安得广厦千万间，大庇天下小猫俱欢颜"), 1)
        for marker in ("#F5F5F7", "#1D1D1F", "clamp(", "min-height: 44px", "@media (prefers-reduced-motion: reduce)"):
            self.assertIn(marker, styles)
        for width in ("1024px", "820px", "430px", "390px", "360px"):
            self.assertIn(width, styles)

    def test_h5_redesign_has_public_product_path(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'data-product-section="home-hero"',
            'data-product-section="primary-actions"',
            'data-product-section="cat-preview"',
            'data-product-section="task-preview"',
            'data-product-section="trust"',
            'id="home-create-cat"',
            'id="home-view-tasks"',
            'id="home-view-cats"',
            "让每一只小猫，",
            "为猫咪建档",
            "查看救助任务",
            "隐私保护",
            "社区审核",
        ):
            self.assertIn(marker, html)
        self.assertIn(".product-shell", styles)
        self.assertIn(".primary-action-grid", styles)
        self.assertIn("renderHomeModuleState", script)

    def test_h5_redesign_uses_module_level_fallbacks(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="home-cats-status"',
            'id="home-tasks-status"',
            'id="home-metrics-status"',
            "state.publicDataStatus",
            'cats: "loading"',
            'tasks: "loading"',
            'communities: "loading"',
            'renderHomeModuleState("cats"',
            'renderHomeModuleState("tasks"',
        ):
            self.assertIn(marker, html + script)
        self.assertNotIn('showStatus(errorText(error), true)', script)

    def test_h5_redesign_responsive_contracts_for_mobile_and_tablet(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            "@media (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (max-width: 360px)",
            "grid-template-columns: repeat(4, minmax(0, 1fr))",
            "aspect-ratio: 4 / 5",
            "padding-bottom: calc(112px + env(safe-area-inset-bottom))",
            "overflow-wrap: anywhere",
        ):
            self.assertIn(marker, styles)
        self.assertNotIn("font-size: 12vw", styles)


if __name__ == "__main__":
    unittest.main()
