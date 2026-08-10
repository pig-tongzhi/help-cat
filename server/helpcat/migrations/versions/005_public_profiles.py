"""Add a stable unique public profile key and backfill story 77."""

from alembic import op
import sqlalchemy as sa


revision = "005_public_profiles"
down_revision = "004_public_metrics"
branch_labels = None
depends_on = None

STORY_MARKER = "2025-06-02 相遇"


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("cats")}
    if "profile_key" not in columns:
        op.add_column("cats", sa.Column("profile_key", sa.String(length=64), nullable=True))
    story_rows = bind.execute(sa.text("""
        SELECT id, profile_key FROM cats
        WHERE profile_key = 'story-77'
           OR (profile_key IS NULL AND nickname = '77' AND location_note LIKE :marker)
        ORDER BY id
    """), {"marker": "%" + STORY_MARKER + "%"}).mappings().all()
    if len(story_rows) > 1:
        raise RuntimeError("multiple legacy cats match story-77; reconcile before migration")
    if story_rows and story_rows[0]["profile_key"] is None:
        bind.execute(
            sa.text("UPDATE cats SET profile_key = 'story-77' WHERE id = :id"),
            {"id": story_rows[0]["id"]},
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("cats")}
    uniques = {item["name"] for item in sa.inspect(bind).get_unique_constraints("cats")}
    if "uq_cats_profile_key" not in indexes | uniques:
        op.create_index("uq_cats_profile_key", "cats", ["profile_key"], unique=True)


def downgrade():
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("cats")}
    if "uq_cats_profile_key" in indexes:
        op.drop_index("uq_cats_profile_key", table_name="cats")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("cats")}
    if "profile_key" in columns:
        with op.batch_alter_table("cats") as batch:
            batch.drop_column("profile_key")
