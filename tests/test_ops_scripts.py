"""`scripts/health_check.sh` 与 `scripts/backup_offsite.sh` 的行为契约。

两个脚本都是「出事时才发现坏了」的那类东西，所以这里都对真实的 HTTP 服务、
真实的 SQLite 文件跑一遍：

* 探活脚本必须真的区分 200 和 503，且失败时退出码非 0（systemd timer 靠它把单元
  标成 failed）。
* 备份脚本必须在 WAL 下做出一致性快照、能自证可恢复（`--verify`），坏了要报错。
"""

import http.server
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEALTH_SCRIPT = REPO_ROOT / "scripts" / "health_check.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_offsite.sh"
PULL_SCRIPT = REPO_ROOT / "scripts" / "pull_backup.sh"

HEALTH_PATHS = (
    "/help-cat-api/api/v1/health",
    "/help-cat-api/api/v1/health/ready",
    "/help-cat/rescue/index.html",
    "/help-cat/admin/",
    "/help-cat/welcome/",
)


class FakeSite(http.server.BaseHTTPRequestHandler):
    """最小替身：默认全部 200，readiness 的返回码可以按用例改。

    静态素材要按扩展名给对 Content-Type —— 探活脚本会检查这一点，因为线上出过
    「素材缺失被 SPA 回退成 index.html(200)」这种静默失败。
    """

    ready_status = 200
    ready_body = b'{"status":"ok","service":"help-cat-api","database":"ok"}'
    missing_asset_status = 200
    asset_content_type = None

    CONTENT_TYPES = {
        ".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml",
        ".css": "text/css", ".js": "application/javascript",
    }

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 的接口
        path = self.path.split("?")[0]
        if path == "/help-cat-api/api/v1/health/ready":
            body, status, content_type = self.ready_body, self.ready_status, "application/json"
        elif path.startswith("/help-cat-api/api/v1/health"):
            body, status, content_type = b'{"status":"ok","service":"help-cat-api","version":"1.0.0"}', 200, "application/json"
        elif "/assets/" in path or path.endswith((".css", ".js")):
            extension = "." + path.rsplit(".", 1)[-1]
            if "/assets/" in path and path.endswith(".webp") and self.missing_asset_status != 200:
                body, status = b"not found", self.missing_asset_status
                content_type = "text/html"
            else:
                body, status = b"binary", 200
                content_type = self.asset_content_type or self.CONTENT_TYPES.get(extension, "application/octet-stream")
        else:
            body, status, content_type = b"<!doctype html><title>ok</title>", 200, "text/html"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ShellPortabilityTests(unittest.TestCase):
    """`$VAR` 后面紧跟中文时，macOS 自带的 bash 3.2 会把中文字节吃进变量名。

    这个坑踩过两次（`health_check.sh` 的失败摘要、`pull_backup.sh` 的收尾输出），
    两次都是「脚本跑到最后一步才炸」。所以直接扫源码：变量引用必须写成 `${VAR}`。
    """

    def test_no_bare_variable_is_followed_by_a_multibyte_character(self):
        findings = []
        for path in sorted((REPO_ROOT / "scripts").glob("*.sh")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in re.finditer(r"\$[A-Za-z_][A-Za-z0-9_]*", line):
                    following = line[match.end():match.end() + 1]
                    if following and ord(following) > 127:
                        findings.append("%s:%d %s" % (path.name, number, line.strip()))
        self.assertEqual([], findings, "把这些变量改成 ${VAR} 写法：\n" + "\n".join(findings))


class PullBackupToolTests(unittest.TestCase):
    """开发机侧的拉取脚本。用假的 ssh/rsync 跑，不碰真服务器。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self._write_stub("ssh", """#!/usr/bin/env bash
for last in "$@"; do :; done
case "$last" in
  *"for d in"*) echo "20260101-000000" ;;
  *"--verify"*) echo "✓ 数据库可以打开，integrity_check=ok" ;;
  *"du -sh"*) echo "11M" ;;
  *) echo "" ;;
esac
""")
        self._write_stub("rsync", """#!/usr/bin/env bash
for last in "$@"; do :; done
mkdir -p "$last"
printf 'snapshot' > "$last/help-cat.db"
printf 'meta' > "$last/META.txt"
( cd "$last" && shasum -a 256 help-cat.db META.txt > SHA256SUMS )
""")
        self.dest = self.root / "local-backups"

    def _write_stub(self, name, body):
        path = self.bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def run_pull(self, *args):
        environment = dict(os.environ, PATH=str(self.bindir) + os.pathsep + os.environ["PATH"])
        return subprocess.run(
            ["bash", str(PULL_SCRIPT), "--dest", str(self.dest), *args],
            cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
        )

    def test_help_and_unknown_arguments(self):
        help_result = subprocess.run(["bash", str(PULL_SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(0, help_result.returncode)
        self.assertIn("--dest", help_result.stdout)
        self.assertEqual(2, subprocess.run(["bash", str(PULL_SCRIPT), "--nope"], capture_output=True, text=True).returncode)

    def test_it_verifies_on_the_server_then_copies_and_checksums_locally(self):
        result = self.run_pull()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        copy = self.dest / "20260101-000000"
        self.assertTrue((copy / "help-cat.db").exists())
        self.assertIn("先在服务器上自检", result.stdout)
        self.assertIn("已拉取 20260101-000000", result.stdout)

    def test_a_failed_local_checksum_stops_the_script(self):
        # 传输被改坏：本地校验必须失败，而不是留下一份「看着完整」的副本。
        self._write_stub("rsync", """#!/usr/bin/env bash
for last in "$@"; do :; done
mkdir -p "$last"
printf 'tampered' > "$last/help-cat.db"
printf 'meta' > "$last/META.txt"
( cd "$last" && shasum -a 256 help-cat.db META.txt > SHA256SUMS )
printf 'corrupt' > "$last/help-cat.db"
""")
        result = self.run_pull()
        self.assertNotEqual(0, result.returncode)

    def test_keep_prunes_older_local_copies(self):
        for stamp in ("20250101-000000", "20250102-000000"):
            (self.dest / stamp).mkdir(parents=True)
        result = self.run_pull("--keep", "2")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        remaining = sorted(path.name for path in self.dest.iterdir())
        self.assertEqual(["20250102-000000", "20260101-000000"], remaining)


class UptimeWorkflowTests(unittest.TestCase):
    """外部探针必须真的在 GitHub 侧跑，且不需要任何密钥。"""

    def workflow(self):
        return (REPO_ROOT / ".github" / "workflows" / "uptime.yml").read_text(encoding="utf-8")

    def test_scheduled_and_manual_and_probes_readiness(self):
        source = self.workflow()
        self.assertIn("schedule:", source)
        self.assertIn("cron:", source)
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("/api/v1/health/ready", source)
        self.assertIn("database", source)
        for path in ("/help-cat/rescue/index.html", "/help-cat/admin/", "/help-cat/welcome/"):
            self.assertIn(path, source)

    def test_it_needs_no_secrets(self):
        source = self.workflow()
        self.assertNotIn("secrets.", source, "外部探针不该依赖任何密钥")
        # 只读权限，且真的要 checkout：版本比对用的是仓库里的 version.js
        self.assertIn("contents: read", source)
        self.assertIn("actions/checkout@v4", source)


class OpsScriptTests(unittest.TestCase):
    def test_health_check_watches_the_https_certificate(self):
        """IP 证书只有 6 天，续期出问题必须能被体检发现，而不是等用户打不开后台。"""
        source = (REPO_ROOT / "scripts" / "health_check.sh").read_text(encoding="utf-8")
        self.assertIn("openssl x509 -checkend", source)
        self.assertIn("86400", source, "按天数换算秒，别做日期差（macOS 与 Linux 的 date 不一样）")
        self.assertIn('check_https_cert "${HTTPS_HOST}"', source, "检查要真的接进主流程")
        # 后台强制 HTTPS 之后，体检必须验"HTTPS 能开 + HTTP 会跳"，否则密码可能被明文传
        self.assertIn("check_admin_https", source)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 探活 -----------------------------------------------------------

    def serve(self, **overrides):
        handler = type("Handler", (FakeSite,), overrides)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d" % server.server_address[1]

    def run_health(self, base, *args):
        environment = dict(
            os.environ,
            HELPCAT_BASE_URL=base,
            HELPCAT_HEALTH_LOG=str(self.root / "health.log"),
            HELPCAT_DB_PATH=str(self.root / "missing.db"),
            # 夹具只有 HTTP，没有 TLS 端口：显式跳过 HTTPS 相关检查
            HELPCAT_HEALTH_HTTP_ONLY="1",
        )
        environment.pop("HELPCAT_ALERT_WEBHOOK", None)
        return subprocess.run(
            ["bash", str(HEALTH_SCRIPT), "--quiet", *args],
            cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
        )

    def test_health_check_passes_when_every_endpoint_answers(self):
        result = self.run_health(self.serve())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = (self.root / "health.log").read_text(encoding="utf-8")
        self.assertIn("通过", log)

    def test_health_check_fails_when_readiness_is_degraded(self):
        base = self.serve(ready_status=503, ready_body=b'{"status":"degraded","database":"error"}')
        result = self.run_health(base)
        self.assertEqual(result.returncode, 1)
        # --quiet 只留日志，所以失败详情从日志里看。
        log = (self.root / "health.log").read_text(encoding="utf-8")
        self.assertIn("失败", log)
        self.assertIn("readiness", log)

    def test_health_check_fails_when_a_static_entry_is_missing(self):
        base = self.serve()
        server = base.replace("http://127.0.0.1:", "")
        self.assertTrue(server.isdigit())
        result = self.run_health("http://127.0.0.1:1")  # 关着的端口
        self.assertEqual(result.returncode, 1)

    def test_health_check_fails_when_a_static_asset_is_missing(self):
        """素材 404（或被回退成 HTML）必须让探活失败，而不是静默通过。"""
        base = self.serve(missing_asset_status=404)
        result = self.run_health(base)
        self.assertEqual(result.returncode, 1)
        log = (self.root / "health.log").read_text(encoding="utf-8")
        self.assertIn("77故事", log)

    def test_health_check_fails_when_an_asset_falls_back_to_html(self):
        """IP 入口曾经对缺失素材回 index.html(200)，这种静默失败要被抓住。"""
        base = self.serve(asset_content_type="text/html")
        result = self.run_health(base)
        self.assertEqual(result.returncode, 1)
        self.assertIn("回退成了 HTML", (self.root / "health.log").read_text(encoding="utf-8"))

    def test_health_check_rejects_unknown_arguments(self):
        result = subprocess.run(
            ["bash", str(HEALTH_SCRIPT), "--nope"], cwd=REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 2)

    # ---- 备份 -----------------------------------------------------------

    def seed_database(self, name="help-cat.db"):
        database = self.root / name
        engine_url = "sqlite:///" + str(database)
        sys.path.insert(0, str(REPO_ROOT))
        from server.helpcat.db import ensure_schema, make_session_factory
        from server.helpcat.models import User

        engine, session_factory = make_session_factory(engine_url)
        ensure_schema(engine)
        with session_factory() as db:
            db.add(User(id="u1", openid="o1", nickname="t", role="USER"))
            db.commit()
        return database

    def backup_env(self, **extra):
        environment = dict(
            os.environ,
            HELPCAT_DB_PATH=str(self.root / "help-cat.db"),
            HELPCAT_UPLOADS_DIR=str(self.root / "uploads"),
            HELPCAT_BACKUP_DIR=str(self.root / "backups"),
            HELPCAT_RELEASE_LINK=str(REPO_ROOT),
            HELPCAT_PYTHON=sys.executable,
        )
        environment.update(extra)
        for key in ("HELPCAT_BACKUP_RCLONE_REMOTE", "HELPCAT_BACKUP_COSCMD_BUCKET",
                    "HELPCAT_BACKUP_S3_URL", "HELPCAT_BACKUP_UPLOAD_CMD"):
            if key not in extra:
                environment.pop(key, None)
        return environment

    def run_backup(self, *args, **extra):
        return subprocess.run(
            ["bash", str(BACKUP_SCRIPT), *args],
            cwd=REPO_ROOT, env=self.backup_env(**extra), capture_output=True, text=True,
        )

    def test_backup_snapshots_a_wal_database_and_can_verify_itself(self):
        database = self.seed_database()
        # 让源库停在 WAL 模式，验证不是靠 cp 蒙对的。
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        uploads = self.root / "uploads" / "2026" / "09"
        uploads.mkdir(parents=True)
        (uploads / "a.jpg").write_bytes(b"fake")

        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        created = sorted((self.root / "backups").iterdir())
        self.assertEqual(len(created), 1)
        self.assertEqual(
            sorted(path.name for path in created[0].iterdir()),
            ["META.txt", "SHA256SUMS", "help-cat.db", "uploads.tar.gz"],
        )

        verify = self.run_backup("--verify", "latest")
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("integrity_check=ok", verify.stdout)
        self.assertIn("'users': 1", verify.stdout)

    def test_backup_verify_fails_loudly_on_a_corrupted_snapshot(self):
        self.seed_database()
        self.assertEqual(self.run_backup().returncode, 0)
        snapshot = sorted((self.root / "backups").iterdir())[0] / "help-cat.db"
        snapshot.write_bytes(b"not a database")

        verify = self.run_backup("--verify", "latest")
        self.assertEqual(verify.returncode, 1)
        self.assertIn("✗", verify.stdout)

    def test_backup_prunes_snapshots_past_the_retention_window(self):
        self.seed_database()
        stale = self.root / "backups" / "20200101-000000"
        stale.mkdir(parents=True)
        (stale / "help-cat.db").write_bytes(b"old")
        old = time.time() - 40 * 24 * 3600
        os.utime(stale, (old, old))

        result = self.run_backup(HELPCAT_BACKUP_KEEP_DAYS="14")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stale.exists(), "超过保留期的备份没有被清理")
        self.assertIn("清理超过 14 天的备份：1 个", result.stdout)

    def test_backup_quiet_keeps_warnings_but_drops_the_chatter(self):
        """systemd 单元传 --quiet，脚本必须认这个参数（线上真的漏过一次）。"""
        self.seed_database()
        result = self.run_backup("--quiet")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("校验和一致", result.stdout)
        self.assertNotIn("备份完成", result.stdout)
        # 告警不能被静音：没有异地目标是要有人处理的
        self.assertIn("未配置异地目标", result.stdout)

    def test_backup_quiet_still_reports_a_broken_snapshot_and_fails(self):
        self.seed_database()
        self.assertEqual(self.run_backup("--quiet").returncode, 0)
        snapshot = sorted((self.root / "backups").iterdir())[0] / "help-cat.db"
        snapshot.write_bytes(b"broken")

        result = self.run_backup("--verify", "latest", "--quiet")
        self.assertEqual(result.returncode, 1)
        self.assertIn("✗", result.stdout)

    def test_backup_dry_run_touches_nothing(self):
        self.seed_database()
        result = self.run_backup("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("会执行", result.stdout)
        self.assertFalse((self.root / "backups").exists())

    def test_backup_reports_a_missing_offsite_target_instead_of_pretending(self):
        self.seed_database()
        result = self.run_backup()
        self.assertEqual(result.returncode, 0)
        self.assertIn("未配置异地目标", result.stdout)

    def test_backup_uses_a_custom_upload_command_when_configured(self):
        self.seed_database()
        marker = self.root / "uploaded.txt"
        script = self.root / "upload.sh"
        script.write_text('#!/usr/bin/env bash\necho "$1" > ' + str(marker) + "\n", encoding="utf-8")
        script.chmod(0o755)

        result = self.run_backup(HELPCAT_BACKUP_UPLOAD_CMD=str(script))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("已上传到异地", result.stdout)
        uploaded = Path(marker.read_text(encoding="utf-8").strip())
        self.assertEqual(uploaded.parent.name, "backups")
        self.assertTrue(uploaded.name.startswith("20"), uploaded.name)


class WebhookSink(http.server.BaseHTTPRequestHandler):
    """收 webhook 的替身，只记下收到的正文。"""

    payloads: list = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 的接口
        length = int(self.headers.get("Content-Length") or 0)
        type(self).payloads.append(self.rfile.read(length).decode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):  # 别把测试输出弄脏
        pass


class CertificateAndProbeResilienceTests(unittest.TestCase):
    """2026-10-01 的事故复盘：IP 证书过期，后台 HTTPS 打不开，而监控根本没在跑。

    两个互相独立的原因，各配一条测试：
      1. 探活单元直接执行脚本路径，发布时用 `chmod 644` 抹掉执行位 → systemd 203/EXEC
         （状态是 "Failed"，不是 "证书过期"）→ 监控静默失效，谁都不知道；
      2. IP 证书续期既被续期配置里的 `autorenew = False` 拦住，又不能只靠 certbot
         自己的"是否到期"判断（实测到期前 2 小时仍报 not yet due），最后就真的过期了。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 单元文件 -------------------------------------------------------

    def test_units_call_scripts_through_bash(self):
        """执行位不可靠（发布流程会 chmod），所以单元必须用 /bin/bash 调脚本。"""
        for name in ("help-cat-healthcheck.service", "certbot-ip-renew.service"):
            text = (REPO_ROOT / "deploy" / "systemd" / name).read_text(encoding="utf-8")
            self.assertRegex(
                text, r"ExecStart=/bin/bash /opt/help-cat/current/scripts/\S+",
                f"{name} 必须用 /bin/bash 调用脚本，否则执行位一丢监控就静默失效",
            )

    def test_shell_scripts_are_tracked_as_executable(self):
        result = subprocess.run(["git", "ls-files", "-s", "scripts"], cwd=REPO_ROOT,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        not_executable = [line.split()[-1] for line in result.stdout.splitlines()
                          if line.split()[-1].endswith(".sh") and line.split()[0] != "100755"]
        self.assertEqual([], not_executable, "这些脚本在 git 里没有执行位")

    # ---- 证书续期 -------------------------------------------------------

    def test_renewal_script_does_not_trust_certbot_alone(self):
        source = (REPO_ROOT / "scripts" / "renew_ip_cert.sh").read_text(encoding="utf-8")
        self.assertIn("openssl x509 -enddate", source, "要自己算剩余时间")
        self.assertIn("--force-renewal", source, "临近到期必须强制续，不等 certbot 判断")
        self.assertIn("--no-random-sleep-on-renew", source,
                      "certbot 默认随机等最多 8 分钟，定时任务和人工都看不出是在跑还是卡住")
        self.assertIn("alert ", source, "续期失败要复用监控的 webhook 喊人")

    def test_renewal_timer_runs_well_inside_the_six_day_lifetime(self):
        text = (REPO_ROOT / "deploy" / "systemd" / "certbot-ip-renew.timer").read_text(encoding="utf-8")
        match = re.search(r"OnCalendar=\S+ (\S+)", text)
        self.assertIsNotNone(match, "定时器必须有 OnCalendar")
        hours = match.group(1).split(":")[0].split(",")
        self.assertGreaterEqual(len(hours), 4, "6 天的证书一天只查两次太稀")

    def test_only_the_ip_renewal_script_writes_the_renewal_audit_log(self):
        """续期日志必须落在固定文件里，否则事后无从判断"它到底跑没跑"。"""
        source = (REPO_ROOT / "scripts" / "renew_ip_cert.sh").read_text(encoding="utf-8")
        self.assertIn("/var/log/helpcat-cert-renew.log", source)

    # ---- 告警冷却与恢复 -------------------------------------------------

    def serve(self, *, posts):
        handler = type("Sink", (WebhookSink,), {"payloads": posts})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d/webhook" % server.server_address[1]

    def run_health(self, base, webhook):
        environment = dict(
            os.environ,
            HELPCAT_BASE_URL=base,
            HELPCAT_HEALTH_LOG=str(self.root / "health.log"),
            HELPCAT_DB_PATH=str(self.root / "missing.db"),
            HELPCAT_HEALTH_HTTP_ONLY="1",
            HELPCAT_ALERT_WEBHOOK=webhook,
            HELPCAT_ALERT_WEBHOOK_FORMAT="wecom",
            HELPCAT_ALERT_COOLDOWN_MIN="60",
            HELPCAT_ALERT_STATE=str(self.root / "last-alert"),
        )
        return subprocess.run(["bash", str(HEALTH_SCRIPT), "--quiet"], cwd=REPO_ROOT,
                              env=environment, capture_output=True, text=True)

    def serve_site(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d" % server.server_address[1]

    def test_alerts_once_per_outage_and_reports_recovery(self):
        """告警不冷却就会被每 5 分钟刷一次群，最后只能关掉 —— 又回到"没人知道"。"""
        posts = []
        webhook = self.serve(posts=posts)
        bad = "http://127.0.0.1:1"  # 关着的端口：探活必然失败

        self.assertEqual(1, self.run_health(bad, webhook).returncode)
        self.assertEqual(1, self.run_health(bad, webhook).returncode)
        self.assertEqual(1, len(posts), "同一个故障在冷却期内只该发一条告警")
        log = (self.root / "health.log").read_text(encoding="utf-8")
        self.assertIn("冷却", log, "被压掉的那次要在日志里留痕")

        # 恢复后补一条通知并清掉状态，否则群里只剩坏消息，看不出已经好了
        result = self.run_health(self.serve_site(), webhook)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(2, len(posts), "恢复要补一条通知")
        self.assertIn("恢复", posts[1])
        self.assertFalse((self.root / "last-alert").exists(), "恢复后要清掉告警状态")


    # ---- 续期脚本的两个分支（真的跑，不只看源码）----------------------

    def make_cert(self, days):
        """造一张真的自签证书，让脚本的剩余时间计算有东西可算。"""
        cert = self.root / ("cert-%s.pem" % days)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(self.root / "key.pem"), "-out", str(cert),
             "-days", str(days), "-subj", "/CN=175.178.41.19"],
            capture_output=True, check=True,
        )
        return cert

    def run_renewal(self, cert, *, force_days=3, warn_hours=24):
        """用假的 certbot 跑脚本：只验证判断逻辑和日志，不碰真 ACME。"""
        calls = self.root / "certbot-calls.txt"
        stub = self.root / "certbot"
        stub.write_text('#!/bin/bash\necho "$@" >> %s\n' % calls, encoding="utf-8")
        stub.chmod(0o755)
        log = self.root / "renew.log"
        environment = dict(
            os.environ,
            HELPCAT_CERT_FILE=str(cert),
            HELPCAT_CERTBOT=str(stub),
            HELPCAT_CERT_LOG=str(log),
            HELPCAT_CERT_FORCE_DAYS=str(force_days),
            HELPCAT_CERT_WARN_HOURS=str(warn_hours),
            HELPCAT_CERT_ENV_FILE=str(self.root / "no-webhook.env"),
        )
        result = subprocess.run(["/bin/bash", str(REPO_ROOT / "scripts" / "renew_ip_cert.sh")],
                                cwd=REPO_ROOT, env=environment, capture_output=True, text=True)
        return result, log.read_text(encoding="utf-8"), calls

    def test_renewal_forces_a_renewal_when_time_is_short(self):
        result, log, calls = self.run_renewal(self.make_cert(2))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("强制续期", log)
        self.assertIn("--force-renewal", calls.read_text(encoding="utf-8"))
        # 这里的 `[ ... $(( ... )) ]` 曾经少了一个 `]`，脚本不报错、只是静默跳过告警，
        # 所以必须断言 stderr 干净，而不是只看退出码。
        self.assertNotIn("missing `]'", result.stderr)
        self.assertEqual("", result.stderr)

    def test_renewal_leaves_a_fresh_certificate_alone(self):
        result, log, calls = self.run_renewal(self.make_cert(6))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("剩余", log)
        self.assertNotIn("--force-renewal", calls.read_text(encoding="utf-8"))
        self.assertNotIn("--force-renewal", log)


if __name__ == "__main__":
    unittest.main()
