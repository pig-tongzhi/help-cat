"""Add explicit QA markers used by public aggregate metrics."""

from alembic import op
import sqlalchemy as sa


revision = "004_public_metrics"
down_revision = "003_scale_integrity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table_name in ("communities", "cats", "tasks"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "is_qa" not in columns:
            op.add_column(
                table_name,
                sa.Column("is_qa", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            )
    bind.execute(sa.text("UPDATE communities SET is_qa = 1 WHERE name LIKE '[QA-%'"))
    bind.execute(sa.text("UPDATE cats SET is_qa = 1 WHERE nickname LIKE '[QA-%'"))
    bind.execute(sa.text("UPDATE tasks SET is_qa = 1 WHERE title LIKE '[QA-%'"))
    for table_name in ("communities", "cats", "tasks"):
        index_name = "ix_%s_is_qa" % table_name
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["is_qa"])


def downgrade():
    bind = op.get_bind()
    for table_name in ("tasks", "cats", "communities"):
        index_name = "ix_%s_is_qa" % table_name
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "is_qa" in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column("is_qa")
