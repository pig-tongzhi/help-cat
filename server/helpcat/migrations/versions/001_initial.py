"""Create Help Cat core schema."""
from alembic import op
from server.helpcat.db import Base
from server.helpcat import models  # noqa: F401

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
