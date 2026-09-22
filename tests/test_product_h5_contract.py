import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProductH5ContractTests(unittest.TestCase):
    """本轮重构后的主页面：导航、入口卡片、投喂、任务闭环、猫咪详情与联系方式。"""

    def h5(self):
        return (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")

    def script(self):
        return (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")

    def styles(self):
        return (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")

    def test_bottom_navigation_has_five_distinct_destinations(self):
        html = self.h5()
        nav = html[html.index('id="bottom-nav"'):]
        nav = nav[:nav.index("</nav>")]
        targets = re.findall(r'data-nav="([^"]+)"', nav)
        self.assertEqual(len(targets), 5, "底部导航应为 5 项：%s" % targets)
        self.assertEqual(len(set(targets)), 5, "底部导航存在重复目标：%s" % targets)
        self.assertEqual(sorted(targets), ["cats", "feeding", "home", "profile", "tasks"])
        for label in ("首页", "投喂", "救助", "猫咪", "我的"):
            self.assertIn("<span>%s</span>" % label, nav)

    def test_home_entry_cards_cover_the_three_pillars(self):
        html = self.h5()
        for marker in (
            "招同行人", 'id="home-create-cat"', 'id="home-view-feeding"',
            'id="home-view-tasks"', 'id="home-view-cats"', 'id="home-contact"',
        ):
            self.assertIn(marker, html)
        for pillar in ("定点投喂", "查看救助任务", "加入我们"):
            self.assertIn(pillar, html)

    def test_metrics_say_accumulating_instead_of_a_fake_zero(self):
        html, script = self.h5(), self.script()
        self.assertIn("正在积累", script)
        self.assertNotIn('value.textContent = "0"', script)
        self.assertIn('id="home-metrics-status"', html)
        self.assertIn('id="home-metrics-note"', html)
        self.assertIn("home-metrics-note", script)
        render_metrics = script[script.index("function renderMetrics()"):script.index("function loadPublicMetrics()")]
        for collection in ("state.cats", "state.tasks", "state.communities"):
            self.assertNotIn(collection, render_metrics)

    def test_feeding_view_is_wired_to_the_feeding_apis(self):
        html, script = self.h5(), self.script()
        for marker in (
            'data-view="feeding"', 'id="feeding-list"', 'id="feeding-stats"',
            'id="my-feeding-logs"', 'id="load-more-feeding"', 'id="refresh-my-feeding"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "/api/v1/feeding-points", "/api/v1/public/feeding-stats",
            "/api/v1/feeding-logs/mine", "data-feeding-checkin", "ensureFeeding", "checkIn",
        ):
            self.assertIn(marker, script)
        self.assertIn(".feeding-card", self.styles())

    def test_cat_cards_open_a_detail_sheet_with_a_public_timeline(self):
        html, script = self.h5(), self.script()
        for marker in ('id="cat-detail-sheet"', 'id="cat-detail-body"'):
            self.assertIn(marker, html)
        for marker in ("openCatDetail", "data-cat-open", "/events", "CAT_EVENT_LABELS", "data-contact-open"):
            self.assertIn(marker, script)
        # 详情只展示公开字段：精确坐标不上页面
        detail = script[script.index("function openCatDetail("):script.index("function loadFeedingStats()")]
        self.assertIn("location_note", detail)
        self.assertNotIn("latitude", detail)
        self.assertNotIn("longitude", detail)

    def test_join_us_sheet_submits_a_lead_with_source_attribution(self):
        html, script = self.h5(), self.script()
        for marker in (
            'id="contact-sheet"', 'id="contact-form"', 'id="contact-value"',
            'id="contact-message"', 'id="contact-status"', 'id="contact-submit"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "/api/v1/public/contact", "/api/v1/public/messages",
            "sourceFromLocation", "openContactSheet", "submitContact",
        ):
            self.assertIn(marker, script)

    def test_task_loop_closes_and_refreshes_my_tasks_after_claiming(self):
        html, script = self.h5(), self.script()
        for marker in (
            'id="my-tasks-section"', 'id="my-task-list"', 'id="task-sheet"', 'id="task-form"',
            'id="task-note"', 'id="task-evidence"', 'id="task-release"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "/api/v1/tasks/mine", "/complete", "/reassign", "data-task-report",
            "openTaskSheet", "submitTaskReport", "releaseTask", "loadMyTasks",
        ):
            self.assertIn(marker, script)
        # 回归保护：领取任务后必须刷新「我领取的任务」，否则刚领的任务不会出现
        claim = script[script.index("function claimTask("):script.index("function submitCommunityCorrection(")]
        self.assertIn("loadMyTasks()", claim)

    def test_an_empty_task_list_offers_a_conversion_path(self):
        script = self.script()
        empty = script[script.index("function taskEmptyCard("):script.index("function emptyCard(")]
        self.assertIn("我想帮忙", empty)
        self.assertIn("data-contact-open", empty)

    def test_server_error_codes_are_mapped_to_chinese(self):
        script = self.script()
        for code in (
            "task_not_yours", "task_already_closed", "task_not_claimed", "feeding_point_not_found",
            "cat_not_found", "too_many_messages", "session_expired", "forbidden",
            "image_too_many_pixels", "community_edit_forbidden", "photo_asset_forbidden",
        ):
            self.assertIn("%s:" % code, script)

    def test_location_hint_only_shows_when_needed(self):
        styles = self.styles()
        self.assertIn(".location-fallback { display: none; }", styles)
        self.assertIn(".location-fallback.visible { display: block; }", styles)

    def test_cat_count_does_not_pretend_to_be_a_total(self):
        script = self.script()
        self.assertIn("已显示 ", script)
        self.assertIn("还有更多", script)

    def test_home_visual_system_and_mobile_stacking(self):
        html, styles = self.h5(), self.styles()
        for marker in (
            "pillar-section", "pillar-card", "quick-action-grid", "impact-band",
            "feeding-teaser", "product-region", "trust-icon",
        ):
            self.assertIn(marker, html + styles)
        # 三支柱在窄屏必须堆叠为单列。这条断言专门守护一个真实踩过的坑：
        # 新加的基础规则写在文件末尾时，会把前面媒体查询里的 1fr 覆盖掉，
        # 导致 390px 下三支柱仍挤成 3 列、文字被压成竖排。
        base = styles.rindex(".primary-action-grid { grid-template-columns: repeat(3")
        narrow = styles.rindex(".primary-action-grid { grid-template-columns: 1fr; }")
        self.assertGreater(narrow, base, "窄屏单列规则必须写在三支柱基础规则之后")

    def test_daily_check_in_gameplay_surface(self):
        html, script, styles = self.h5(), self.script(), self.styles()
        for marker in (
            'id="streak-card"', 'id="streak-days"', 'id="streak-week"', 'id="streak-next"',
            'id="feeding-today-line"', 'id="sort-nearby"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "/feeding-logs/mine/summary", "loadFeedingSummary", "renderStreakWeek", "sortNearby",
            "needs_feed", "distance_m", "formatDistance", "sort=today",
        ):
            self.assertIn(marker, script)
        for marker in (".streak-card", ".streak-day.is-fed", ".feeding-badge", ".feeding-distance"):
            self.assertIn(marker, styles)
        # 与三支柱同理：连续打卡卡的窄屏堆叠规则必须写在基础规则之后，
        # 否则 390px 下仍是两列、7 天格会溢出视口（实测超出 45px）。
        base = styles.rindex("grid-template-columns: minmax(0, 150px) minmax(0, 1fr);")
        narrow = styles.rindex(".streak-card { grid-template-columns: 1fr; }")
        self.assertGreater(narrow, base, "窄屏堆叠规则必须写在连续打卡卡基础规则之后")

    def test_mobile_h5_compatibility_basics(self):
        styles = self.styles()
        for marker in (
            "text-size-adjust: 100%",   # iOS 不擅自放大文字
            "min-height: 100dvh",       # 地址栏收放不再抖动
            "touch-action: manipulation",  # 去掉点击延迟
            "@media (hover: none)",     # 触摸设备禁用 hover 粘滞
            "font-size: 16px",          # 防 iOS 聚焦输入框时整页放大
            "overscroll-behavior: contain",
        ):
            self.assertIn(marker, styles)

    def test_feeding_log_can_capture_food_and_a_photo(self):
        html, script, styles = self.h5(), self.script(), self.styles()
        for marker in (
            'id="feed-sheet"', 'id="feed-food"', 'id="feed-note"', 'id="feed-photo"',
            'id="feed-submit"', 'id="feed-sheet-intro"',
        ):
            self.assertIn(marker, html)
        for marker in ("openFeedSheet", "submitFeed", "data-feeding-detail", "food_note", "photo_asset_id"):
            self.assertIn(marker, script)
        self.assertIn(".feeding-actions", styles)
        # 快速打卡这一条路径必须保留，不能因为多了详情弹层而变慢
        self.assertIn("data-feeding-checkin", script)

    def test_weekly_rota_surface_is_wired(self):
        html, script, styles = self.h5(), self.script(), self.styles()
        for marker in (
            'id="shift-grid"', 'id="shift-head-row"', 'id="shift-grid-body"',
            'id="shift-summary"', 'id="refresh-shifts"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "/api/v1/feeding-shifts", "loadShifts", "renderShiftGrid", "claimShift", "releaseShift",
            "data-shift-claim", "data-shift-release", "shanghaiDateKey", "todayShiftLine",
        ):
            self.assertIn(marker, script)
        for marker in (".shift-panel", ".shift-cell.is-mine", ".shift-cell.is-done", ".shift-scroll"):
            self.assertIn(marker, styles)
        # 排班格在手机上要能横向滚动，且触摸目标不小于 44px
        self.assertIn("min-height: 44px", styles)

    def test_top_navigation_shows_the_current_section(self):
        html, script, styles = self.h5(), self.script(), self.styles()
        self.assertIn('class="desktop-nav"', html)
        self.assertIn(".desktop-nav button:hover", styles)
        self.assertIn(".desktop-nav button.active", styles)
        # 顶部导航与底部导航共用同一份选中态
        self.assertIn(".nav-item, .desktop-nav button", script)
        self.assertIn("button.dataset.nav === state.view", script)

    def test_archive_and_tasks_lead_above_the_cat_creation_form(self):
        html = self.h5()
        # 猫咪档案与救助任务要是最显眼的两个入口，且必须排在「为猫咪建档」（表单入口）之前
        form = html.index('id="home-create-cat"')
        self.assertLess(html.index('id="home-view-cats"'), form, "查看猫咪档案要排在建档表单之前")
        self.assertLess(html.index('id="home-view-tasks"'), form, "查看救助任务要排在建档表单之前")
        pillars = html[html.index('class="primary-action-grid"'):html.index('class="quick-action-grid"')]
        self.assertIn('id="home-view-cats"', pillars)
        self.assertIn('id="home-view-tasks"', pillars)

    def test_the_77_story_has_only_two_entries_on_the_home_page(self):
        html = self.h5()
        # 首屏大按钮 + 顶部导航各一个就够了；此前还有一张重复的小卡片，同一屏出现三次
        self.assertEqual(html.count('data-nav="story-77"'), 2, "首页只保留「首屏按钮 + 顶部导航」两个 77 入口")
        self.assertNotIn('id="home-story-entry"', html)
        quick = html[html.index('class="quick-action-grid"'):html.index("</section>", html.index('class="quick-action-grid"'))]
        self.assertNotIn("77 的故事", quick, "小卡片行不该再有 77 的入口")

    def test_hero_primary_action_is_a_filled_button(self):
        import re

        styles = self.styles()
        rules = re.findall(r"\.editorial-story-link\s*\{(?P<body>[^}]*)\}", styles)
        self.assertTrue(rules, "缺少 .editorial-story-link 规则")
        # 取最后一条：级联里后写的生效
        self.assertIn("background: var(--brand)", rules[-1])
        self.assertIn("border-radius: 999px", rules[-1])

    def test_dialogs_move_focus_in_and_give_it_back(self):
        html, script = self.h5(), self.script()
        # 弹层必须是 </main> 之后的兄弟节点：给背景加 inert 才不会把弹层自己一起冻住
        self.assertLess(html.index("</main>"), html.index('id="sheet-backdrop"'), "弹层不能放进 main 里面")
        self.assertIn("sheetReturnFocus", script, "关闭弹层要把焦点还给触发元素")
        self.assertIn("function setSheetBackgroundInert", script)
        self.assertIn("el.inert = on", script)
        self.assertIn('el.setAttribute("aria-hidden", "true")', script)
        self.assertIn('sheet.querySelector("[data-close-sheet]")', script, "没有输入框的弹层也要把焦点收进来")
        self.assertIn("document.contains(sheetReturnFocus)", script, "归还焦点前要确认元素还在文档里")
        # 打开与关闭必须成对地切换背景隔离，否则关闭后整页会变成不可交互的「死页」
        open_sheet = script[script.index("function openSheet"):script.index("function closeSheets")]
        close_sheet = script[script.index("function closeSheets"):script.index("function openAuth")]
        self.assertIn("setSheetBackgroundInert(true)", open_sheet)
        self.assertIn("setSheetBackgroundInert(false)", close_sheet)

    def test_no_leftover_browser_probe_files(self):
        leftovers = sorted(p.name for p in (ROOT / "app" / "rescue").iterdir() if p.name.startswith("__"))
        self.assertEqual(leftovers, [], "请删除临时探针文件：%s" % leftovers)


class AdminProductPanelContractTests(unittest.TestCase):
    """管理后台新增的投喂点、救助任务、救助记录与猫咪时间线入口。"""

    def html(self):
        return (ROOT / "admin" / "index.html").read_text(encoding="utf-8")

    def script(self):
        return (ROOT / "admin" / "app.js").read_text(encoding="utf-8")

    def test_console_exposes_the_new_panels(self):
        html = self.html()
        for marker in (
            'data-section="feeding"', 'data-section="tasks"', 'data-section="impact"',
            'data-admin-section="feeding"', 'data-admin-section="tasks"', 'data-admin-section="impact"',
            'id="feeding-form"', 'id="feeding-name"', 'id="feeding-points"',
            'id="task-form"', 'id="task-title"', 'id="admin-tasks"',
            'id="impact-form"', 'id="impact-kind"', 'id="impact-events"',
            'id="load-more-admin-feeding"', 'id="load-more-admin-tasks"', 'id="load-more-admin-impact"',
            'data-task-filter=""',
        ):
            self.assertIn(marker, html)

    def test_console_wires_the_new_actions(self):
        script = self.script()
        for marker in (
            "/api/v1/admin/feeding-points", "/api/v1/admin/tasks", "/api/v1/admin/impact-events",
            "data-feeding-action", "data-task-action", "data-task-reason",
            "data-impact-action", "data-cat-action", "data-cat-event-form",
        ):
            self.assertIn(marker, script)

    def test_admin_can_set_feeding_point_coordinates(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        for marker in ('id="feeding-latitude"', 'id="feeding-longitude"'):
            self.assertIn(marker, html)
        for marker in (
            "data-feeding-coords-form", "data-feeding-lat", "data-feeding-lng",
            "submitFeedingCoords", "已设坐标", "未设坐标",
            "latitude: latitude ? Number(latitude) : null",
        ):
            self.assertIn(marker, script)

    def test_console_keeps_the_visitor_message_board(self):
        script = self.script()
        for marker in ("/api/v1/admin/messages", "data-message-action", "data-message-filter"):
            self.assertIn(marker, script)


class DevPreviewToolContractTests(unittest.TestCase):
    """本地预览服务器必须原样转发 HTTP 方法。

    曾经写成 `do_PATCH = do_POST`，而 do_POST 固定用 proxy("POST")，
    于是所有 PATCH 请求被降级成 POST，后端返回 405，
    让社区纠错、投喂点暂停/归档、补坐标等在本地「假失败」。
    """

    def test_dev_preview_forwards_the_real_http_methods(self):
        source = (ROOT / "scripts" / "dev_preview.py").read_text(encoding="utf-8")
        for method in ("PATCH", "PUT", "DELETE", "OPTIONS"):
            self.assertIn('return self.proxy("%s")' % method, source)
        # 只匹配代码行，避免注释里提到这个写法时误报
        self.assertNotRegex(source, r"(?m)^\s*do_PATCH\s*=\s*do_POST")


class ServerRouteContractTests(unittest.TestCase):
    """新增接口必须真的注册在服务端，避免前后端契约漂移。"""

    def test_server_defines_the_feeding_task_and_timeline_routes(self):
        source = (ROOT / "server" / "helpcat" / "app.py").read_text(encoding="utf-8")
        for route in (
            '@app.get("/api/v1/feeding-points")',
            '@app.post("/api/v1/feeding-points/{point_id}/logs", status_code=201)',
            '@app.get("/api/v1/feeding-logs/mine")',
            '@app.get("/api/v1/public/feeding-stats")',
            '@app.post("/api/v1/admin/feeding-points", status_code=201)',
            '@app.patch("/api/v1/admin/feeding-points/{point_id}")',
            '@app.get("/api/v1/admin/feeding-points")',
            '@app.get("/api/v1/tasks/mine")',
            '@app.post("/api/v1/tasks/{task_id}/complete")',
            '@app.post("/api/v1/tasks/{task_id}/cancel")',
            '@app.post("/api/v1/tasks/{task_id}/reassign")',
            '@app.get("/api/v1/admin/tasks")',
            '@app.get("/api/v1/cats/{cat_id}/events")',
            '@app.post("/api/v1/admin/cats/{cat_id}/events", status_code=201)',
        ):
            self.assertIn(route, source)


if __name__ == "__main__":
    unittest.main()
