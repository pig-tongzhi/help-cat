"""Add scale-oriented integrity and idempotency constraints."""

from alembic import op
import sqlalchemy as sa


revision = "003_scale_integrity"
down_revision = "002_community_candidates"
branch_labels = None
depends_on = None

TERMINAL_STATUSES = "'MERGED','REJECTED','ARCHIVED','HIDDEN'"


def _reconcile_live_name_collisions(bind):
    groups = bind.execute(sa.text(f"""
        SELECT city, district, normalized_name
        FROM communities
        WHERE status NOT IN ({TERMINAL_STATUSES})
        GROUP BY city, district, normalized_name
        HAVING COUNT(*) > 1
    """)).mappings().all()
    for group in groups:
        rows = bind.execute(sa.text(f"""
            SELECT id, status FROM communities
            WHERE city = :city AND district = :district AND normalized_name = :normalized_name
              AND status NOT IN ({TERMINAL_STATUSES})
            ORDER BY CASE WHEN status = 'ACTIVE' THEN 0 ELSE 1 END, created_at, id
        """), group).mappings().all()
        target_id = rows[0]["id"]
        for duplicate in rows[1:]:
            bind.execute(sa.text("UPDATE cats SET community_id = :target, version = COALESCE(version, 1) + 1 WHERE community_id = :source"), {
                "target": target_id, "source": duplicate["id"],
            })
            bind.execute(sa.text("""
                UPDATE communities
                SET status = 'MERGED', merged_into_id = :target, version = COALESCE(version, 1) + 1
                WHERE id = :source
            """), {"target": target_id, "source": duplicate["id"]})


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cat_columns = {column["name"] for column in inspector.get_columns("cats")}
    if "idempotency_key" not in cat_columns:
        op.add_column("cats", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    if "version" not in cat_columns:
        op.add_column("cats", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    _reconcile_live_name_collisions(bind)

    foreign_keys = sa.inspect(bind).get_foreign_keys("communities")
    has_merge_fk = any("merged_into_id" in (item.get("constrained_columns") or []) for item in foreign_keys)
    if not has_merge_fk:
        with op.batch_alter_table("communities", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_communities_merged_into_id", "communities", ["merged_into_id"], ["id"]
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("communities")}
    if "uq_communities_live_location_name" not in indexes:
        op.create_index(
            "uq_communities_live_location_name",
            "communities",
            ["city", "district", "normalized_name"],
            unique=True,
            sqlite_where=sa.text(f"status NOT IN ({TERMINAL_STATUSES})"),
            postgresql_where=sa.text(f"status NOT IN ({TERMINAL_STATUSES})"),
        )
    cat_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("cats")}
    cat_uniques = {item["name"] for item in sa.inspect(bind).get_unique_constraints("cats")}
    if "uq_cats_actor_idempotency" not in cat_indexes | cat_uniques:
        op.create_index(
            "uq_cats_actor_idempotency", "cats", ["created_by", "idempotency_key"], unique=True
        )


def downgrade():
    bind = op.get_bind()
    community_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("communities")}
    if "uq_communities_live_location_name" in community_indexes:
        op.drop_index("uq_communities_live_location_name", table_name="communities")
    cat_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("cats")}
    if "uq_cats_actor_idempotency" in cat_indexes:
        op.drop_index("uq_cats_actor_idempotency", table_name="cats")
    with op.batch_alter_table("communities", recreate="always") as batch:
        batch.drop_constraint("fk_communities_merged_into_id", type_="foreignkey")
    with op.batch_alter_table("cats") as batch:
        batch.drop_column("version")
        batch.drop_column("idempotency_key")
