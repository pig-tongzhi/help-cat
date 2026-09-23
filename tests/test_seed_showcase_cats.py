"""演示猫档案（showcase）的写入、幂等与回收，以及素材来源的可追溯性。

这批数据的特殊性在于它**真的会出现在公开页面上**，所以测试盯三件事：

1. 写进去的档案必须是「已审核 + 已发布 + 非 QA + 有照片」，否则等于白写；
2. 必须能整体干净收回 —— 脚本删不干净就会在线上留下孤儿媒体文件；
3. 素材必须有来源与许可记录（`SOURCES.md`），否则将来换上真实照片时没人知道
   这些图是从哪来的、能不能继续用。
"""

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "seed_showcase_cats.py"
PHOTO_DIR = REPO_ROOT / "scripts" / "showcase_photos"


class ShowcaseSeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / "help-cat.db"
        self.storage = self.root / "uploads"
        self.storage.mkdir()
        sys.path.insert(0, str(REPO_ROOT / "server"))
        from server.helpcat.db import ensure_schema, make_session_factory
        from server.helpcat.models import Community, User

        engine, session_factory = make_session_factory("sqlite:///" + str(self.database))
        ensure_schema(engine)
        with session_factory() as db:
            db.add(User(id="u-admin", openid="openid-admin", role="SUPER_ADMIN", nickname="管理员"))
            for index, name in enumerate(("银湖街道", "上林南路", "缙云大厦")):
                db.add(Community(
                    id="community-%d" % index, city="杭州市", district="富阳区", street="银湖街道",
                    name=name, normalized_name=name, status="ACTIVE", created_by="u-admin",
                ))
            db.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def run_seed(self, *args):
        environment = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "server"))
        return subprocess.run(
            [sys.executable, str(SCRIPT),
             "--database-url", "sqlite:///" + str(self.database),
             "--storage-root", str(self.storage), *args],
            cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
        )

    def catalog(self):
        with sqlite3.connect(self.database) as connection:
            rows = connection.execute(
                "SELECT id, nickname, review_status, visibility_status, is_qa, health_status, "
                "photo_asset_id, community_id FROM cats WHERE id LIKE 'showcase-%' ORDER BY id"
            ).fetchall()
        return rows

    # ---- 预览与幂等 -----------------------------------------------------

    def test_list_only_previews_and_writes_nothing(self):
        result = self.run_seed("--list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("将新建: showcase-cat-00", result.stdout)
        self.assertEqual([], self.catalog())
        self.assertEqual([], list(self.storage.iterdir()))

    def test_execute_creates_public_ready_cats_every_time_but_only_once(self):
        first = self.run_seed("--execute")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        rows = self.catalog()
        self.assertEqual(8, len(rows))
        for _id, nickname, review, visibility, is_qa, health, photo, community in rows:
            self.assertEqual("APPROVED", review)
            self.assertEqual("ACTIVE", visibility)
            self.assertEqual(0, is_qa)
            self.assertTrue(photo, "%s 没有照片" % nickname)
            self.assertTrue(community)
            self.assertIn(health, {"HEALTHY", "NEEDS_HELP", "UNKNOWN"})
        # 名字要是正常猫名，不能带 QA / 测试 这类标记
        for row in rows:
            self.assertNotIn("[QA-", row[1])
            self.assertNotIn("测试", row[1])
            self.assertTrue(re.match(r"^[\u4e00-\u9fa5]{2,4}$", row[1]), "名字不像正常猫名：%s" % row[1])

        second = self.run_seed("--execute")
        self.assertEqual(second.returncode, 0)
        self.assertIn("已存在跳过: showcase-cat-00", second.stdout)
        self.assertEqual(8, len(self.catalog()), "重跑不应重复创建")
        self.assertEqual(16, len(list(self.storage.iterdir())), "8 张原图 + 8 张缩略图")

    def test_the_seeded_cats_are_visible_through_the_public_api(self):
        self.assertEqual(0, self.run_seed("--execute").returncode)
        from fastapi.testclient import TestClient

        from server.helpcat.app import create_app

        app = create_app("sqlite:///" + str(self.database), storage_root=self.storage)
        with TestClient(app) as client:
            body = client.get("/api/v1/cats", params={"limit": 50}).json()
            nicknames = sorted(item["nickname"] for item in body["items"])
            self.assertEqual(
                sorted(["汤圆", "花卷", "灰灰", "年糕", "豆花", "墨镜", "虎子", "大橘"]), nicknames,
                "演示档案应当全部、且只有它们出现在公开列表里",
            )
            first = body["items"][0]
            media = client.get("/api/v1/media/%s" % first["photo_asset_id"], params={"variant": "thumb"})
            self.assertEqual(200, media.status_code)

    # ---- 回收 -----------------------------------------------------------

    def test_cleanup_removes_rows_and_files_but_keeps_other_cats(self):
        self.assertEqual(0, self.run_seed("--execute").returncode)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO cats (id, community_id, code, nickname, living_status, health_status,"
                " location_note, review_status, visibility_status, is_qa, version, created_by,"
                " created_at, updated_at) VALUES ('keep-me', 'community-0', 'HC-KEEP', '留守猫', '',"
                " 'UNKNOWN', 'x', 'APPROVED', 'ACTIVE', 0, 1, 'u-admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            connection.commit()

        preview = self.run_seed("--cleanup")
        self.assertEqual(0, preview.returncode)
        self.assertIn("这是预览", preview.stdout)
        self.assertEqual(8, len(self.catalog()), "预览不应删任何东西")

        executed = self.run_seed("--cleanup", "--execute")
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
        self.assertEqual([], self.catalog())
        self.assertEqual([], list(self.storage.iterdir()), "媒体文件没删干净")
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM cats WHERE id='keep-me'").fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM media_assets WHERE id LIKE 'showcase-%'").fetchone()[0])


class ShowcasePhotoProvenanceTests(unittest.TestCase):
    """素材必须先有来源和许可记录，再拿去当线上照片。"""

    def sources(self):
        return (PHOTO_DIR / "SOURCES.md").read_text(encoding="utf-8")

    def test_every_photo_is_listed_with_a_free_license(self):
        text = self.sources()
        photos = sorted(path.name for path in PHOTO_DIR.glob("*.webp"))
        self.assertTrue(photos, "演示照片目录是空的")
        for name in photos:
            self.assertIn(name, text, "%s 没有记来源" % name)
        self.assertIn("CC0", text)
        self.assertIn("公有领域", text)

    def test_photos_are_card_shaped_and_small_enough_to_commit(self):
        from PIL import Image

        for path in sorted(PHOTO_DIR.glob("*.webp")):
            with Image.open(path) as image:
                ratio = image.width / image.height
                # 站内猫卡是 4:5；素材已经裁好，CSS 再裁就不会切到主体。
                self.assertLessEqual(ratio, 4 / 5 + 0.001, "%s 不是竖版（%sx%s）" % (path.name, image.width, image.height))
                self.assertGreaterEqual(image.width, 900, "%s 分辨率太低" % path.name)
            self.assertLess(path.stat().st_size, 600 * 1024, "%s 体积过大" % path.name)


class PurgeTestCatsTests(unittest.TestCase):
    """一次性数据修复脚本：默认不删、删对目标、再跑一次是 no-op。"""

    PURGE_IDS = ("b92ee3daf3d24c6cb982ac11954daae1", "e14422dd")
    MOVE_ID = "c690d3a0"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / "help-cat.db"
        self.storage = self.root / "uploads"
        self.storage.mkdir()
        sys.path.insert(0, str(REPO_ROOT / "server"))
        from server.helpcat.db import ensure_schema, make_session_factory
        from server.helpcat.models import Cat, Community, MediaAsset, User

        engine, session_factory = make_session_factory("sqlite:///" + str(self.database))
        ensure_schema(engine)
        with session_factory() as db:
            db.add(User(id="u-admin", openid="openid-admin", role="SUPER_ADMIN", nickname="管理员"))
            db.add(Community(id="qa-community", city="杭州市", district="富阳区", street="银湖街道",
                             name="[QA-20260801] 星河家园", normalized_name="qa", status="ARCHIVED",
                             is_qa=True, created_by="u-admin"))
            db.add(Community(id="real-community", city="杭州市", district="富阳区", street="银湖街道",
                             name="银湖街道", normalized_name="银湖街道", status="ACTIVE", created_by="u-admin"))
            for index, cat_id in enumerate(self.PURGE_IDS):
                asset = MediaAsset(id="media-%d" % index, object_key="object-%d.jpg" % index,
                                   content_type="image/jpeg", byte_size=10, created_by="u-admin")
                db.add(asset)
                db.add(Cat(id=cat_id, community_id="qa-community", code="HC-%d" % index, nickname="测试%d" % index,
                           living_status="", health_status="UNKNOWN", location_note="x",
                           review_status="APPROVED", visibility_status="ACTIVE", is_qa=False, version=1,
                           created_by="u-admin", photo_asset_id=asset.id))
            db.add(Cat(id=self.MOVE_ID, community_id="qa-community", code="HC-MOVE", nickname="三花",
                       living_status="", health_status="UNKNOWN", location_note="x",
                       review_status="APPROVED", visibility_status="ACTIVE", is_qa=False, version=1,
                       created_by="u-admin"))
            db.add(Cat(id="keep-me", community_id="real-community", code="HC-KEEP", nickname="留守猫",
                       living_status="", health_status="UNKNOWN", location_note="x",
                       review_status="APPROVED", visibility_status="ACTIVE", is_qa=False, version=1,
                       created_by="u-admin"))
            db.commit()
        for index in range(len(self.PURGE_IDS)):
            (self.storage / ("object-%d.jpg" % index)).write_bytes(b"x")
            (self.storage / ("object-%d.thumb.webp" % index)).write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def run_purge(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "purge_test_cats.py"),
             "--database-url", "sqlite:///" + str(self.database),
             "--storage-root", str(self.storage), *args],
            cwd=REPO_ROOT, env=dict(os.environ, PYTHONPATH=str(REPO_ROOT / "server")),
            capture_output=True, text=True,
        )

    def state(self):
        with sqlite3.connect(self.database) as connection:
            cats = dict(connection.execute("SELECT id, community_id FROM cats").fetchall())
            versions = dict(connection.execute("SELECT id, version FROM cats").fetchall())
            media = {row[0] for row in connection.execute("SELECT id FROM media_assets").fetchall()}
        return cats, versions, media

    def test_preview_deletes_nothing(self):
        result = self.run_purge()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("这是预览", result.stdout)
        cats, _versions, media = self.state()
        self.assertEqual(4, len(cats))
        self.assertEqual(2, len(media))

    def test_execute_removes_only_the_named_cats_and_moves_the_keeper(self):
        result = self.run_purge("--execute")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        cats, versions, media = self.state()
        self.assertEqual({"c690d3a0", "keep-me"}, set(cats))
        self.assertEqual("real-community", cats["c690d3a0"], "有猫照片的档案应被移到 ACTIVE 小区")
        self.assertEqual("real-community", cats["keep-me"], "无关档案不该被动")
        self.assertEqual(set(), media, "被删档案的媒体行应一并清掉")
        self.assertEqual([], list(self.storage.iterdir()), "媒体文件应一并清掉")

        # 再跑一次是 no-op：不升版本、不再写审计
        before = versions["c690d3a0"]
        again = self.run_purge("--execute")
        self.assertEqual(0, again.returncode)
        self.assertIn("'reassigned': 0", again.stdout, "重跑不该再动小区归属")
        _cats, versions_after, _media = self.state()
        self.assertEqual(before, versions_after["c690d3a0"])


class PurgeAuditLogTests(unittest.TestCase):
    def test_purge_writes_an_audit_row_naming_what_it_removed(self):
        """删档案必须留下痕迹：谁删的、删了哪些、为什么。"""
        source = (REPO_ROOT / "scripts" / "purge_test_cats.py").read_text(encoding="utf-8")
        self.assertIn('action="PURGE"', source)
        self.assertIn('action="REASSIGN"', source)
        self.assertIn("--execute", source)
        for marker in ("头像不是猫", "QA fixture"):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
