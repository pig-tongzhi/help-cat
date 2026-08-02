import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text

from server.helpcat.db import ensure_schema, make_session_factory


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

    def test_alembic_environment_honors_deployment_database_url(self):
        environment = Path("server/helpcat/migrations/env.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("HELPCAT_DATABASE_URL")', environment)
        self.assertIn('config.set_main_option("sqlalchemy.url"', environment)


if __name__ == "__main__":
    unittest.main()
