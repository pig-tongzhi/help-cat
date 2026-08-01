import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect

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


if __name__ == "__main__":
    unittest.main()
