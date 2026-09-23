"""Add feeding points, feeding check-ins, cat timelines, and task closure.

Every step is guarded: revision ``001_initial`` builds its tables from the
current models, so a database that starts from the models already has these
tables and columns.  The guards keep the chain replayable from an empty
database, from a legacy pilot database, and from one already at head.
"""

from alembic import op
import sqlalchemy as sa


revision = "008_feeding_and_task_closure"
down_revision = "007_lead_messages"
branch_labels = None
depends_on = None

TASK_CLOSURE_COLUMNS = (
    ("completed_at", lambda: sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)),
    ("completion_note", lambda: sa.Column("completion_note", sa.Text(), nullable=False, server_default="")),
    ("evidence_asset_id", lambda: sa.Column("evidence_asset_id", sa.String(length=32), nullable=True)),
    ("cancelled_at", lambda: sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)),
    ("cancel_reason", lambda: sa.Column("cancel_reason", sa.Text(), nullable=False, server_default="")),
)


def _create_feeding_points():
    op.create_table(
        "feeding_points",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("community_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("location_note", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("feeding_time", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("caretaker_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE','PAUSED','ARCHIVED')", name="ck_feeding_points_status"),
        sa.ForeignKeyConstraint(["community_id"], ["communities.id"], name="fk_feeding_points_community_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_feeding_points_created_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feeding_points_name", "feeding_points", ["name"])
    op.create_index("ix_feeding_points_community_id", "feeding_points", ["community_id"])
    op.create_index("ix_feeding_points_status", "feeding_points", ["status"])
    op.create_index("ix_feeding_points_is_qa", "feeding_points", ["is_qa"])
    op.create_index("ix_feeding_points_created_at", "feeding_points", ["created_at"])


def _create_feeding_logs():
    op.create_table(
        "feeding_logs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("point_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("fed_on", sa.String(length=10), nullable=False),
        sa.Column("fed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("food_note", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("photo_asset_id", sa.String(length=32), nullable=True),
        sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["point_id"], ["feeding_points.id"], name="fk_feeding_logs_point_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_feeding_logs_user_id"),
        sa.ForeignKeyConstraint(["photo_asset_id"], ["media_assets.id"], name="fk_feeding_logs_photo_asset_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("point_id", "user_id", "fed_on", name="uq_feeding_logs_point_user_day"),
    )
    op.create_index("ix_feeding_logs_point_id", "feeding_logs", ["point_id"])
    op.create_index("ix_feeding_logs_user_id", "feeding_logs", ["user_id"])
    op.create_index("ix_feeding_logs_fed_on", "feeding_logs", ["fed_on"])
    op.create_index("ix_feeding_logs_is_qa", "feeding_logs", ["is_qa"])
    op.create_index("ix_feeding_logs_created_at", "feeding_logs", ["created_at"])


def _create_cat_events():
    op.create_table(
        "cat_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("cat_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('RESCUE','FEED','MEDICAL','CHECKUP','ADOPTED','NOTE')",
            name="ck_cat_events_kind",
        ),
        sa.ForeignKeyConstraint(["cat_id"], ["cats.id"], name="fk_cat_events_cat_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_cat_events_created_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cat_events_cat_id", "cat_events", ["cat_id"])
    op.create_index("ix_cat_events_kind", "cat_events", ["kind"])
    op.create_index("ix_cat_events_occurred_at", "cat_events", ["occurred_at"])
    op.create_index("ix_cat_events_is_qa", "cat_events", ["is_qa"])


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("feeding_points"):
        _create_feeding_points()
    if not inspector.has_table("feeding_logs"):
        _create_feeding_logs()
    if not inspector.has_table("cat_events"):
        _create_cat_events()

    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    for name, factory in TASK_CLOSURE_COLUMNS:
        if name not in task_columns:
            op.add_column("tasks", factory())


def downgrade():
    task_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tasks")}
    for name, _factory in reversed(TASK_CLOSURE_COLUMNS):
        if name in task_columns:
            op.drop_column("tasks", name)

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("cat_events"):
        op.drop_index("ix_cat_events_is_qa", table_name="cat_events")
        op.drop_index("ix_cat_events_occurred_at", table_name="cat_events")
        op.drop_index("ix_cat_events_kind", table_name="cat_events")
        op.drop_index("ix_cat_events_cat_id", table_name="cat_events")
        op.drop_table("cat_events")

    if inspector.has_table("feeding_logs"):
        op.drop_index("ix_feeding_logs_created_at", table_name="feeding_logs")
        op.drop_index("ix_feeding_logs_is_qa", table_name="feeding_logs")
        op.drop_index("ix_feeding_logs_fed_on", table_name="feeding_logs")
        op.drop_index("ix_feeding_logs_user_id", table_name="feeding_logs")
        op.drop_index("ix_feeding_logs_point_id", table_name="feeding_logs")
        op.drop_table("feeding_logs")

    if inspector.has_table("feeding_points"):
        op.drop_index("ix_feeding_points_created_at", table_name="feeding_points")
        op.drop_index("ix_feeding_points_is_qa", table_name="feeding_points")
        op.drop_index("ix_feeding_points_status", table_name="feeding_points")
        op.drop_index("ix_feeding_points_community_id", table_name="feeding_points")
        op.drop_index("ix_feeding_points_name", table_name="feeding_points")
        op.drop_table("feeding_points")
