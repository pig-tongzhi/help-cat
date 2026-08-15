"""Add community candidate governance fields."""

from alembic import op
import sqlalchemy as sa

from server.helpcat.community_rules import normalize_community_name


revision = "002_community_candidates"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("communities")}
    if "normalized_name" not in columns:
        op.add_column("communities", sa.Column("normalized_name", sa.String(length=120), nullable=False, server_default=""))
    if "review_note" not in columns:
        op.add_column("communities", sa.Column("review_note", sa.Text(), nullable=False, server_default=""))
    if "merged_into_id" not in columns:
        op.add_column("communities", sa.Column("merged_into_id", sa.String(length=32), nullable=True))
    if "version" not in columns:
        op.add_column("communities", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    rows = bind.execute(sa.text("SELECT id, name FROM communities WHERE normalized_name = '' OR normalized_name IS NULL")).mappings()
    for row in rows:
        try:
            normalized_name = normalize_community_name(row["name"])
        except ValueError:
            normalized_name = "community-" + row["id"]
        bind.execute(
            sa.text("UPDATE communities SET normalized_name = :normalized_name WHERE id = :id"),
            {"normalized_name": normalized_name, "id": row["id"]},
        )
    bind.execute(sa.text("UPDATE communities SET version = 1 WHERE version IS NULL OR version < 1"))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("communities")}
    if "ix_communities_normalized_name" not in indexes:
        op.create_index("ix_communities_normalized_name", "communities", ["normalized_name"])
    if "ix_communities_merged_into_id" not in indexes:
        op.create_index("ix_communities_merged_into_id", "communities", ["merged_into_id"])


def downgrade():
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("communities")}
    if "ix_communities_merged_into_id" in indexes:
        op.drop_index("ix_communities_merged_into_id", table_name="communities")
    if "ix_communities_normalized_name" in indexes:
        op.drop_index("ix_communities_normalized_name", table_name="communities")
    with op.batch_alter_table("communities") as batch:
        batch.drop_column("version")
        batch.drop_column("merged_into_id")
        batch.drop_column("review_note")
        batch.drop_column("normalized_name")
