"""Schema 单一来源的守护测试。

在 2026-09-23 的架构评估里，「Alembic 11 个迁移 + `ensure_schema` 里 23 条裸 ALTER」
被判为两个真相来源。实际后果比「容易漂移」更硬：

* `001_initial` 用 `Base.metadata.create_all()` 建**当时全部**的表，于是 006/007/008/010
  的 `create_table` 必然撞 "table already exists"，从空库跑 `alembic upgrade head`
  根本跑不完（CI 里那条被 deselect 的基线失败就是它）。
* 反过来，只跑迁移建出来的库又缺 `users.username` / `users.password_hash` /
  `sessions.revoked_at` —— 这些列只写在 `ensure_schema` 里。

所以这里的断言都是真跑迁移，而不是检查字符串：

1. 空库 `alembic upgrade head` 后的结构必须和 models 完全一致（用 `compare_metadata`，
   它能抓出「模型加了列/索引但迁移忘了加」这类漂移 —— 本轮就抓出了 006 漏建的
   `ix_impact_events_created_by`）。
2. 一个「已经拥有完整当前结构」的库，`stamp base` 后重放整条迁移链也必须成功，
   这条覆盖所有迁移的幂等守卫。
3. 老的 pilot 库（只有 communities/cats 两张旧表 + 待合并的数据）升级到 head 后，
   数据合并不丢、补齐的列到位。
4. `ensure_schema` 跑在迁移后的库上是 no-op。
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from server.helpcat import models  # noqa: F401 - register every table on Base.metadata
from server.helpcat.db import Base, ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "server" / "helpcat" / "migrations"

LEGACY_SCRIPT = """
CREATE TABLE communities (
    id VARCHAR(32) PRIMARY KEY, city VARCHAR(40), district VARCHAR(40), street VARCHAR(80),
    name VARCHAR(120), status VARCHAR(20), created_by VARCHAR(32), reviewed_by VARCHAR(32),
    created_at DATETIME, updated_at DATETIME
);
CREATE TABLE cats (
    id VARCHAR(32) PRIMARY KEY, community_id VARCHAR(32), code VARCHAR(40), nickname VARCHAR(80),
    living_status VARCHAR(80), health_status VARCHAR(80), location_note VARCHAR(240),
    latitude FLOAT, longitude FLOAT, photo_asset_id VARCHAR(32), review_status VARCHAR(20),
    visibility_status VARCHAR(20), created_by VARCHAR(32), created_at DATETIME, updated_at DATETIME
);
INSERT INTO communities VALUES
    ('c1','杭州市','富阳区','银湖街道','星河 家园','ACTIVE','u1',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
    ('c2','杭州市','富阳区','银湖街道','星河　家园','PENDING_REVIEW','u1',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
INSERT INTO cats VALUES
    ('cat1','c2','HC-LEGACY','旧猫','','UNKNOWN','北门',NULL,NULL,NULL,'PENDING_REVIEW','ACTIVE','u1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
"""


class SchemaSingleSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 脚手架 ---------------------------------------------------------

    def alembic_ini(self):
        """A trimmed ini: a caller-supplied config must not need the logging sections."""
        config = self.root / "alembic.ini"
        config.write_text(
            "[alembic]\nscript_location = " + str(MIGRATIONS) + "\nprepend_sys_path = "
            + str(REPO_ROOT) + "\nsqlalchemy.url = sqlite:///unused.db\n",
            encoding="utf-8",
        )
        return config

    def alembic(self, database, *args):
        environment = dict(os.environ, HELPCAT_DATABASE_URL="sqlite:///" + str(database))
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(self.alembic_ini()), *args],
            cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
        )

    def head_revision(self):
        directory = ScriptDirectory(str(MIGRATIONS))
        directory.chdir = None
        return directory.get_current_head()

    def upgraded_from_empty(self, name="fresh.db"):
        database = self.root / name
        result = self.alembic(database, "upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stderr)
        return database

    def schema_drift(self, database):
        """What the database still lacks compared with the models."""
        engine = create_engine("sqlite:///" + str(database))
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            return compare_metadata(context, Base.metadata)

    def columns_of(self, database, table):
        engine = create_engine("sqlite:///" + str(database))
        return {column["name"] for column in inspect(engine).get_columns(table)}

    # ---- 1. 空库跑完迁移 == models --------------------------------------

    def test_migrations_alone_build_the_schema_the_models_describe(self):
        database = self.upgraded_from_empty()
        self.assertEqual(self.schema_drift(database), [])
        with sqlite3.connect(database) as connection:
            self.assertEqual(
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                self.head_revision(),
            )

    # ---- 2. 整条链对「已有完整结构」的库也必须幂等 ----------------------

    def test_migration_chain_replays_against_a_database_that_already_has_everything(self):
        database = self.root / "already.db"
        ensure_schema(create_engine("sqlite:///" + str(database)))
        stamped = self.alembic(database, "stamp", "base")
        self.assertEqual(stamped.returncode, 0, stamped.stderr)

        result = self.alembic(database, "upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.schema_drift(database), [])

    # ---- 3. 老 pilot 库升级 ---------------------------------------------

    def test_legacy_pilot_database_upgrades_and_keeps_its_reconciled_data(self):
        database = self.root / "legacy.db"
        with sqlite3.connect(database) as connection:
            connection.executescript(LEGACY_SCRIPT)

        result = self.alembic(database, "upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(database) as connection:
            self.assertEqual(
                connection.execute("SELECT community_id FROM cats WHERE id='cat1'").fetchone()[0], "c1"
            )
            self.assertEqual(
                connection.execute("SELECT status, merged_into_id FROM communities WHERE id='c2'").fetchone(),
                ("MERGED", "c1"),
            )
        # 只写在 ensure_schema 里的那几列，现在迁移也会补上。
        self.assertLessEqual({"username", "password_hash"}, self.columns_of(database, "users"))
        self.assertIn("revoked_at", self.columns_of(database, "sessions"))

    # ---- 4. 运行期兜底不再是第二个真相来源 ------------------------------

    def test_ensure_schema_is_a_no_op_on_a_migrated_database(self):
        database = self.upgraded_from_empty("boot.db")
        engine = create_engine("sqlite:///" + str(database))
        ensure_schema(engine)
        ensure_schema(engine)  # 幂等
        self.assertEqual(self.schema_drift(database), [])

    def test_legacy_repairs_have_a_single_definition_shared_by_both_paths(self):
        from server.helpcat import schema_upgrades

        self.assertTrue(schema_upgrades.LEGACY_COLUMNS)
        source = (MIGRATIONS / "versions" / "011_bootstrap_parity.py").read_text(encoding="utf-8")
        self.assertIn("apply_legacy_upgrades", source)
        # 裸 ALTER 不允许再写回 ensure_schema。
        db_source = (REPO_ROOT / "server" / "helpcat" / "db.py").read_text(encoding="utf-8")
        self.assertNotIn("ALTER TABLE", db_source.upper())


if __name__ == "__main__":
    unittest.main()
