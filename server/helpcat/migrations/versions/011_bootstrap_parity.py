"""Replay the hand-written bootstrap repairs as a real migration.

``ensure_schema`` used to add these columns to a live database at startup,
which made it a second schema source of truth and left any database built from
the migrations alone without them.  The list now lives in
``helpcat.schema_upgrades`` and both paths replay exactly it, so a database
that runs ``alembic upgrade head`` ends up with the same shape the models
expect.

The repair is forward-only: it only ever adds what is missing, so it is a no-op
on the production database (which already has these columns) and on a database
built from the current models.
"""

from alembic import op

from server.helpcat.schema_upgrades import apply_legacy_upgrades

revision = "011_bootstrap_parity"
down_revision = "010_feeding_shifts"
branch_labels = None
depends_on = None


def upgrade():
    apply_legacy_upgrades(op.get_bind())


def downgrade():
    # Dropping the columns again would fail on every database that legitimately
    # has them from its model definition, so this repair has no rollback.
    pass
