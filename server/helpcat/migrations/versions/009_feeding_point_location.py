"""Add optional coordinates to feeding points."""

from alembic import op
import sqlalchemy as sa


revision = "009_feeding_point_location"
down_revision = "008_feeding_and_task_closure"
branch_labels = None
depends_on = None

COLUMNS = (
    ("latitude", lambda: sa.Column("latitude", sa.Float(), nullable=True)),
    ("longitude", lambda: sa.Column("longitude", sa.Float(), nullable=True)),
)


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("feeding_points")}
    for name, factory in COLUMNS:
        if name not in existing:
            op.add_column("feeding_points", factory())


def downgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("feeding_points")}
    for name, _factory in reversed(COLUMNS):
        if name in existing:
            op.drop_column("feeding_points", name)
