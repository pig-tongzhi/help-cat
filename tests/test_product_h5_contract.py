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

    def test_console_keeps_the_visitor_message_board(self):
        script = self.script()
        for marker in ("/api/v1/admin/messages", "data-message-action", "data-message-filter"):
            self.assertIn(marker, script)


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
