"""`scripts/bump_version.sh` 的行为契约。

这个脚本存在的唯一理由是「改了静态资源忘了升版本号，已访问用户拿不到新版」，
所以测试盯的是它会真做的事：认得出全部版本线、dry-run 不落盘、版本号漂移时报错、
升级后文件内容真的换了。
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "bump_version.sh"


def run(*args, cwd=REPO_ROOT):
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True
    )


class BumpVersionScriptTests(unittest.TestCase):
    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), "bump_version.sh 必须可执行")

    def test_help_lists_the_supported_invocations(self):
        result = run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for token in ("--next", "--dry-run", "--check"):
            self.assertIn(token, result.stdout)

    def test_check_passes_on_the_current_tree(self):
        result = run("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("primary", result.stdout)
        self.assertIn("welcome", result.stdout)

    def test_next_dry_run_covers_every_stream_and_writes_nothing(self):
        before = {path: path.read_bytes() for path in self.versioned_files()}
        result = run("--next", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("app/rescue/index.html", result.stdout)
        self.assertIn("admin/index.html", result.stdout)
        self.assertIn("app/welcome/index.html", result.stdout)
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes(), "%s 被 dry-run 改动了" % path)

    def test_rejects_an_explicit_version_equal_to_the_current_one(self):
        current = self.current_primary()
        result = run(current)
        self.assertEqual(result.returncode, 2)
        self.assertIn("等于没升", result.stderr)

    def test_rejects_unknown_arguments(self):
        result = run("--nope")
        self.assertEqual(result.returncode, 2)

    def test_bump_rewrites_every_reference_including_the_pinned_tests(self):
        """在临时副本里真跑一次，避免污染工作树。"""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            # 只拷脚本关心的文件即可，脚本用相对路径定位它们。
            for relative in (
                "scripts/bump_version.sh",
                "app/rescue/index.html",
                "app/rescue/version.js",
                "app/rescue/manifest.webmanifest",
                "app/welcome/index.html",
                "admin/index.html",
                "tests/test_rescue_h5_contract.py",
                "tests/test_commercial_frontends.py",
            ):
                target = copy / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO_ROOT / relative, target)

            old = self.current_primary()
            new = re.sub(r"-r(\d+)$", lambda m: "-r%d" % (int(m.group(1)) + 1), old)
            result = subprocess.run(
                ["bash", "scripts/bump_version.sh", new], cwd=copy, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in (
                "app/rescue/index.html",
                "app/rescue/version.js",
                "app/rescue/manifest.webmanifest",
                "admin/index.html",
                "tests/test_rescue_h5_contract.py",
                "tests/test_commercial_frontends.py",
            ):
                text = (copy / relative).read_text(encoding="utf-8")
                self.assertNotIn(old, text, "%s 还留着旧版本号" % relative)
                self.assertIn(new, text, "%s 没被升到新版本号" % relative)
            # 欢迎页是另一条版本线，跟着自己的计数器 +1。
            self.assertIn("-r5", (copy / "app/welcome/index.html").read_text(encoding="utf-8"))

    # ---- 辅助 -----------------------------------------------------------

    def current_primary(self):
        text = (REPO_ROOT / "app" / "rescue" / "version.js").read_text(encoding="utf-8")
        return re.search(r'CURRENT_VERSION = "([^"]+)"', text).group(1)

    def versioned_files(self):
        return [
            REPO_ROOT / relative
            for relative in (
                "app/rescue/index.html",
                "app/rescue/version.js",
                "app/rescue/manifest.webmanifest",
                "admin/index.html",
                "app/welcome/index.html",
                "tests/test_rescue_h5_contract.py",
                "tests/test_commercial_frontends.py",
            )
        ]


if __name__ == "__main__":
    unittest.main()
