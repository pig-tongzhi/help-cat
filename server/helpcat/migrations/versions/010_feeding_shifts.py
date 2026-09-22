"""Add daily feeding shifts claimed by volunteers."""

from alembic import op
import sqlalchemy as sa


revision = "010_feeding_shifts"
down_revision = "009_feeding_point_location"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feeding_shifts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("point_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("shift_date", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="CLAIMED"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('CLAIMED','DONE','CANCELLED')", name="ck_feeding_shifts_status"),
        sa.ForeignKeyConstraint(["point_id"], ["feeding_points.id"], name="fk_feeding_shifts_point_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_feeding_shifts_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feeding_shifts_point_id", "feeding_shifts", ["point_id"])
    op.create_index("ix_feeding_shifts_user_id", "feeding_shifts", ["user_id"])
    op.create_index("ix_feeding_shifts_shift_date", "feeding_shifts", ["shift_date"])
    op.create_index("ix_feeding_shifts_status", "feeding_shifts", ["status"])
    op.create_index("ix_feeding_shifts_is_qa", "feeding_shifts", ["is_qa"])
    op.create_index(
        "uq_feeding_shifts_live_slot", "feeding_shifts", ["point_id", "shift_date"],
        unique=True,
        sqlite_where=sa.text("status != 'CANCELLED'"),
        postgresql_where=sa.text("status != 'CANCELLED'"),
    )


def downgrade():
    op.drop_index("uq_feeding_shifts_live_slot", table_name="feeding_shifts")
    op.drop_index("ix_feeding_shifts_is_qa", table_name="feeding_shifts")
    op.drop_index("ix_feeding_shifts_status", table_name="feeding_shifts")
    op.drop_index("ix_feeding_shifts_shift_date", table_name="feeding_shifts")
    op.drop_index("ix_feeding_shifts_user_id", table_name="feeding_shifts")
    op.drop_index("ix_feeding_shifts_point_id", table_name="feeding_shifts")
    op.drop_table("feeding_shifts")
