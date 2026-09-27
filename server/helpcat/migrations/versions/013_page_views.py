"""Add the per-day page view counter that feeds the admin dashboard.

One row per day per page kind, incremented in place, so the table stays tiny no
matter how much traffic arrives. Kept out of audit_logs because that table's
actor_id is a non-null foreign key and visitors are anonymous.
"""

from alembic import op
import sqlalchemy as sa


revision = "013_page_views"
down_revision = "012_login_attempts"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("page_views"):
        return
    op.create_table(
        "page_views",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "kind", name="uq_page_views_day_kind"),
    )
    op.create_index("ix_page_views_day", "page_views", ["day"])
    op.create_index("ix_page_views_kind", "page_views", ["kind"])


def downgrade():
    op.drop_index("ix_page_views_kind", table_name="page_views")
    op.drop_index("ix_page_views_day", table_name="page_views")
    op.drop_table("page_views")
