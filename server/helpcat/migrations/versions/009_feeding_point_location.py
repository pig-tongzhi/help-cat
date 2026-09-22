"""Add optional coordinates to feeding points."""

from alembic import op
import sqlalchemy as sa


revision = "009_feeding_point_location"
down_revision = "008_feeding_and_task_closure"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("feeding_points", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("feeding_points", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("feeding_points", "longitude")
    op.drop_column("feeding_points", "latitude")
