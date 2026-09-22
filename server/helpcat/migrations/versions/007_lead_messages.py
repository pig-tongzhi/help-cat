"""Add lead messages captured by the public welcome page."""

from alembic import op
import sqlalchemy as sa


revision = "007_lead_messages"
down_revision = "006_impact_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lead_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("contact_type", sa.String(length=20), nullable=False, server_default="WECHAT"),
        sa.Column("contact", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="NEW"),
        sa.Column("admin_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("client_ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("handled_by", sa.String(length=32), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "contact_type IN ('WECHAT','PHONE','QQ','OTHER')",
            name="ck_lead_messages_contact_type",
        ),
        sa.CheckConstraint("status IN ('NEW','CONTACTED','CLOSED')", name="ck_lead_messages_status"),
        sa.ForeignKeyConstraint(["handled_by"], ["users.id"], name="fk_lead_messages_handled_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_messages_contact", "lead_messages", ["contact"])
    op.create_index("ix_lead_messages_contact_type", "lead_messages", ["contact_type"])
    op.create_index("ix_lead_messages_created_at", "lead_messages", ["created_at"])
    op.create_index("ix_lead_messages_is_qa", "lead_messages", ["is_qa"])
    op.create_index("ix_lead_messages_status", "lead_messages", ["status"])


def downgrade():
    op.drop_index("ix_lead_messages_status", table_name="lead_messages")
    op.drop_index("ix_lead_messages_is_qa", table_name="lead_messages")
    op.drop_index("ix_lead_messages_created_at", table_name="lead_messages")
    op.drop_index("ix_lead_messages_contact_type", table_name="lead_messages")
    op.drop_index("ix_lead_messages_contact", table_name="lead_messages")
    op.drop_table("lead_messages")
