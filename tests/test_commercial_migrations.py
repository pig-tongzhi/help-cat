import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm.exc import StaleDataError

from server.helpcat.db import ensure_schema, make_session_factory
from server.helpcat.models import Cat, Community, User


class CommercialMigrationTests(unittest.TestCase):
    def test_bootstrap_schema_contains_auth_location_and_revocation_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, _ = make_session_factory("sqlite:///" + str(Path(tmp) / "help-cat.db"))
            ensure_schema(engine)
            self.assertIn("username", {item["name"] for item in inspect(engine).get_columns("users")})
            self.assertIn("revoked_at", {item["name"] for item in inspect(engine).get_columns("sessions")})
            cat_columns = {item["name"] for item in inspect(engine).get_columns("cats")}
            self.assertTrue({"latitude", "longitude"}.issubset(cat_columns))
            self.assertTrue({"version", "idempotency_key"}.issubset(cat_columns))
            self.assertIn("is_qa", cat_columns)
            self.assertIn("is_qa", {item["name"] for item in inspect(engine).get_columns("communities")})
            self.assertIn("is_qa", {item["name"] for item in inspect(engine).get_columns("tasks")})

    def test_bootstrap_schema_adds_and_backfills_community_candidate_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, _ = make_session_factory("sqlite:///" + str(Path(tmp) / "help-cat.db"))
            ensure_schema(engine)
            columns = {item["name"] for item in inspect(engine).get_columns("communities")}
            self.assertTrue({"normalized_name", "review_note", "merged_into_id", "version"}.issubset(columns))
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users (id, openid, role, status, nickname, created_at, last_login_at) "
                        "VALUES ('u1', 'openid-u1', 'USER', 'ACTIVE', '用户', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO communities "
                        "(id, city, district, street, name, status, created_by, created_at, updated_at, normalized_name, review_note, version) "
                        "VALUES ('c1', '杭州市', '富阳区', '银湖街道', ' 星河　家园！ ', 'PENDING_REVIEW', 'u1', "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '', '', 1)"
                    )
                )
                connection.execute(text("UPDATE communities SET normalized_name = '', version = 0 WHERE id = 'c1'"))
            ensure_schema(engine)
            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT normalized_name, version FROM communities WHERE id = 'c1'")
                ).one()
            self.assertEqual(row.normalized_name, "星河家园")
            self.assertEqual(row.version, 1)

    def test_candidate_migration_revision_exists(self):
        migration = Path("server/helpcat/migrations/versions/002_community_candidates.py").read_text(encoding="utf-8")
        self.assertIn('revision = "002_community_candidates"', migration)
        self.assertIn('down_revision = "001_initial"', migration)
        for column in ("normalized_name", "review_note", "merged_into_id", "version"):
            self.assertIn(column, migration)

    def test_integrity_migration_declares_foreign_key_unique_live_name_and_idempotency(self):
        migration = Path("server/helpcat/migrations/versions/003_scale_integrity.py").read_text(encoding="utf-8")
        for marker in (
            "fk_communities_merged_into_id",
            "uq_communities_live_location_name",
            "uq_cats_actor_idempotency",
            "idempotency_key",
            "batch_alter_table",
        ):
            self.assertIn(marker, migration)

    def test_public_metrics_migration_adds_and_backfills_explicit_qa_markers(self):
        migration = Path("server/helpcat/migrations/versions/004_public_metrics.py").read_text(encoding="utf-8")
        self.assertIn('revision = "004_public_metrics"', migration)
        self.assertIn('down_revision = "003_scale_integrity"', migration)
        for marker in ("communities", "cats", "tasks", "is_qa", "[QA-"):
            self.assertIn(marker, migration)

    def test_public_profile_migration_declares_unique_key_and_legacy_77_backfill(self):
        path = Path("server/helpcat/migrations/versions/005_public_profiles.py")
        self.assertTrue(path.is_file())
        migration = path.read_text(encoding="utf-8")
        self.assertIn('revision = "005_public_profiles"', migration)
        self.assertIn('down_revision = "004_public_metrics"', migration)
        for marker in ("profile_key", "uq_cats_profile_key", "story-77", "2025-06-02 相遇"):
            self.assertIn(marker, migration)

    def test_impact_event_migration_declares_auditable_ledger(self):
        path = Path("server/helpcat/migrations/versions/006_impact_events.py")
        self.assertTrue(path.is_file())
        migration = path.read_text(encoding="utf-8")
        self.assertIn('revision = "006_impact_events"', migration)
        self.assertIn('down_revision = "005_public_profiles"', migration)
        for marker in (
            "impact_events", "RESCUED", "ADOPTED", "MEDICAL", "SUPPORTER",
            "ck_impact_events_kind", "ck_impact_events_amount_positive",
            "occurred_at", "reversed_at", "reversed_by", "is_qa",
            "ix_impact_events_is_qa", "ix_impact_events_kind",
        ):
            self.assertIn(marker, migration)

        with tempfile.TemporaryDirectory() as tmp:
            engine, _ = make_session_factory("sqlite:///" + str(Path(tmp) / "impact.db"))
            ensure_schema(engine)
            self.assertIn("impact_events", inspect(engine).get_table_names())
            columns = {item["name"] for item in inspect(engine).get_columns("impact_events")}
            self.assertTrue({
                "kind", "amount", "note", "occurred_at", "created_by",
                "reversed_at", "reversed_by", "is_qa",
            }.issubset(columns))

    def test_bootstrap_backfills_one_legacy_story_profile_and_rejects_duplicate_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, session_factory = make_session_factory("sqlite:///" + str(Path(tmp) / "one.db"))
            ensure_schema(engine)
            self.assertIn("profile_key", {item["name"] for item in inspect(engine).get_columns("cats")})
            with session_factory() as db:
                db.add(User(id="u-story", openid="story-openid", role="ADMIN", status="ACTIVE", nickname="管理员"))
                db.add(Community(
                    id="c-story", name="故事小区", normalized_name="故事小区", street="银湖街道",
                    status="ACTIVE", created_by="u-story",
                ))
                db.add(Cat(
                    id="cat-story", community_id="c-story", code="HC-STORY", nickname="77",
                    location_note="公开位置已保护；2025-06-02 相遇", created_by="u-story",
                ))
                db.commit()
            ensure_schema(engine)
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT profile_key FROM cats WHERE id='cat-story'")).scalar_one(), "story-77")

        with tempfile.TemporaryDirectory() as tmp:
            engine, session_factory = make_session_factory("sqlite:///" + str(Path(tmp) / "duplicate.db"))
            ensure_schema(engine)
            with session_factory() as db:
                db.add(User(id="u-duplicate", openid="duplicate-openid", role="ADMIN", status="ACTIVE", nickname="管理员"))
                db.add(Community(
                    id="c-duplicate", name="重复故事小区", normalized_name="重复故事小区", street="银湖街道",
                    status="ACTIVE", created_by="u-duplicate",
                ))
                for index in range(2):
                    db.add(Cat(
                        id="cat-duplicate-%d" % index, community_id="c-duplicate", code="HC-DUP-%d" % index,
                        nickname="77", location_note="公开位置已保护；2025-06-02 相遇", created_by="u-duplicate",
                    ))
                db.commit()
            with self.assertRaisesRegex(RuntimeError, "multiple legacy cats match story-77"):
                ensure_schema(engine)

    def test_alembic_environment_honors_deployment_database_url(self):
        environment = Path("server/helpcat/migrations/env.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("HELPCAT_DATABASE_URL")', environment)
        self.assertIn('config.set_main_option("sqlalchemy.url"', environment)

    def test_mapper_version_predicate_rejects_two_transactions_updating_same_community(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, session_factory = make_session_factory("sqlite:///" + str(Path(tmp) / "versioned.db"))
            ensure_schema(engine)
            with session_factory() as setup:
                setup.add(User(id="u-version", openid="version-openid", role="ADMIN", status="ACTIVE", nickname="管理员"))
                setup.add(Community(
                    id="c-version", name="版本并发小区", normalized_name="版本并发小区",
                    street="银湖街道", status="PENDING_REVIEW", created_by="u-version",
                ))
                setup.commit()
            first = session_factory()
            second = session_factory()
            try:
                first_item = first.get(Community, "c-version")
                second_item = second.get(Community, "c-version")
                first_item.status = "ACTIVE"
                first_item.version += 1
                second_item.status = "REJECTED"
                second_item.version += 1
                first.commit()
                with self.assertRaises(StaleDataError):
                    second.commit()
            finally:
                first.close()
                second.close()

    @unittest.skipUnless(importlib.util.find_spec("alembic"), "Alembic is installed in production/CI, not the macOS system Python")
    def test_alembic_upgrade_executes_against_legacy_sqlite_and_reconciles_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "legacy.db"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
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
                """)
            config = Path(tmp) / "alembic.ini"
            config.write_text(
                "[alembic]\nscript_location = " + str((Path.cwd() / "server/helpcat/migrations").resolve()) +
                "\nprepend_sys_path = " + str(Path.cwd().resolve()) + "\nsqlalchemy.url = sqlite:///unused.db\n",
                encoding="utf-8",
            )
            environment = dict(os.environ, HELPCAT_DATABASE_URL="sqlite:///" + str(database))
            subprocess.run(
                [sys.executable, "-m", "alembic", "-c", str(config), "upgrade", "head"],
                check=True, cwd=Path.cwd(), env=environment, capture_output=True, text=True,
            )
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchone()[0], "003_scale_integrity")
                self.assertEqual(connection.execute("SELECT community_id FROM cats WHERE id='cat1'").fetchone()[0], "c1")
                self.assertEqual(connection.execute("SELECT status, merged_into_id FROM communities WHERE id='c2'").fetchone(), ("MERGED", "c1"))
                self.assertTrue(any(row[2] == "merged_into_id" for row in connection.execute("PRAGMA foreign_key_list(communities)")))
                self.assertIn("uq_communities_live_location_name", {row[1] for row in connection.execute("PRAGMA index_list(communities)")})
                self.assertIn("uq_cats_actor_idempotency", {row[1] for row in connection.execute("PRAGMA index_list(cats)")})


if __name__ == "__main__":
    unittest.main()
