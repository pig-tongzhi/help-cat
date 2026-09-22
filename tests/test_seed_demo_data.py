"""守护演示数据播种器的取景窗口。

存在的理由很具体：第一版把打卡记录的 `day_offset` 写成了 `0..9`，
而日期是按 `today + offset` 算的 —— 结果整批打卡被播到了**未来 10 天**。
未来的打卡在语义上不成立，而且会把公开统计搞歪：首页的「今日打卡」有数字、
「近 7 天打卡」却几乎为 0，连续打卡点阵的过去几天全空。
这个 bug 只能靠"窗口方向"的断言拦住，所以单独写在这里。
"""

import unittest
from pathlib import Path

from scripts.seed_demo_data import (
    DEMO_LOGS,
    DEMO_PREFIX,
    DEMO_SHIFTS,
)

# 期望的打卡窗口长度：今天往前 10 天（含今天）。写在测试里而不是从脚本导入，
# 这样脚本悄悄改窗口时测试会红，而不是跟着一起变。
LOG_DAYS = 10


class DemoSeedDataWindowTests(unittest.TestCase):
    def test_feeding_logs_cover_the_last_days_ending_today(self):
        offsets = sorted({entry[1] for entry in DEMO_LOGS})
        self.assertEqual(offsets, list(range(-(LOG_DAYS - 1), 1)),
                         "打卡必须覆盖「今天往前 LOG_DAYS 天」，且不含未来日期")
        self.assertEqual(offsets[-1], 0, "必须包含今天，否则「今日打卡」是空的")
        self.assertLessEqual(max(offsets), 0, "不允许出现未来日期的打卡")

    def test_every_day_in_the_window_has_a_check_in(self):
        by_day = {}
        for entry in DEMO_LOGS:
            by_day.setdefault(entry[1], 0)
            by_day[entry[1]] += 1
        self.assertEqual(len(by_day), LOG_DAYS, "窗口内每天都要有打卡，否则点阵有空洞")
        for offset, count in by_day.items():
            self.assertGreaterEqual(count, 1, "第 %d 天没有打卡" % offset)

    def test_shifts_are_today_or_later(self):
        offsets = sorted({entry[1] for entry in DEMO_SHIFTS})
        self.assertGreaterEqual(min(offsets), 0, "排班只应安排在今天及以后")
        self.assertLessEqual(max(offsets), 3, "排班窗口保持今天到 +3 天")

    def test_every_seeded_row_id_uses_the_demo_prefix(self):
        groups = (DEMO_LOGS, DEMO_SHIFTS)
        for group in groups:
            for entry in group:
                self.assertTrue(entry[0].startswith(DEMO_PREFIX),
                                "%s 不带 %s 前缀，回收时无法精确定位" % (entry[0], DEMO_PREFIX))

    def test_no_row_is_dated_in_the_future_helper(self):
        """窗口方向的核心断言：offset <= 0 等价于 fed_on <= 今天。"""
        future = [entry[0] for entry in DEMO_LOGS if entry[1] > 0]
        self.assertEqual(future, [], "这些打卡被排到了未来：%s" % future)


if __name__ == "__main__":
    unittest.main()
