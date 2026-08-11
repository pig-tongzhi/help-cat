"""Add an auditable, reversible ledger for public impact totals."""

from alembic import op
import sqlalchemy as sa


revision = "006_impact_events"
down_revision = "005_public_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "impact_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.String(length=32), nullable=True),
        sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint(
            "kind IN ('RESCUED','ADOPTED','MEDICAL','SUPPORTER')",
            name="ck_impact_events_kind",
        ),
        sa.CheckConstraint("amount > 0", name="ck_impact_events_amount_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_impact_events_created_by"),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"], name="fk_impact_events_reversed_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_impact_events_kind", "impact_events", ["kind"])
    op.create_index("ix_impact_events_is_qa", "impact_events", ["is_qa"])
    op.create_index("ix_impact_events_occurred_at", "impact_events", ["occurred_at"])
    op.create_index("ix_impact_events_reversed_at", "impact_events", ["reversed_at"])


def downgrade():
    op.drop_index("ix_impact_events_reversed_at", table_name="impact_events")
    op.drop_index("ix_impact_events_occurred_at", table_name="impact_events")
    op.drop_index("ix_impact_events_is_qa", table_name="impact_events")
    op.drop_index("ix_impact_events_kind", table_name="impact_events")
    op.drop_table("impact_events")
