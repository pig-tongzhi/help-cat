"""Add the login attempt counter used to throttle password guessing.

Kept out of audit_logs on purpose: audit rows carry an actor_id foreign key and a
failed login may not correspond to any account at all.
"""

from alembic import op
import sqlalchemy as sa


revision = "012_login_attempts"
down_revision = "011_bootstrap_parity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("login_attempts"):
        return
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_username", "login_attempts", ["username"])
    op.create_index("ix_login_attempts_client_ip", "login_attempts", ["client_ip"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])


def downgrade():
    op.drop_index("ix_login_attempts_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_client_ip", table_name="login_attempts")
    op.drop_index("ix_login_attempts_username", table_name="login_attempts")
    op.drop_table("login_attempts")
