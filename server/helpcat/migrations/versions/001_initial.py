"""Create the Help Cat core schema.

Only the tables that existed at this revision are created here; every later
table is created by its own migration.  Building them from the *current* models
instead (the previous behaviour) meant later migrations then hit
"table already exists", so the chain could not be replayed from an empty
database at all.

The tables are still defined by the models, which stay the single source of
truth for schema; the guards keep this revision replayable against a legacy
pilot database that already has some of them.
"""

from alembic import op
import sqlalchemy as sa

from server.helpcat.db import Base
from server.helpcat import models  # noqa: F401

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

CORE_TABLES = ("users", "sessions", "communities", "cats", "daily_cat_quotas", "media_assets", "audit_logs", "tasks")


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = [Base.metadata.tables[name] for name in CORE_TABLES if name in Base.metadata.tables]
    missing = [table for table in tables if not inspector.has_table(table.name)]
    if missing:
        Base.metadata.create_all(bind=bind, tables=missing)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [Base.metadata.tables[name] for name in reversed(CORE_TABLES) if inspector.has_table(name)]
    if existing:
        Base.metadata.drop_all(bind=bind, tables=existing)
