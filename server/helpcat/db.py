from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_session_factory(database_url):
    kwargs = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_schema(engine):
    """Small forward-only bootstrap for the existing pilot SQLite database.

    Production changes must be promoted through Alembic; this guard keeps the
    already deployed pilot database readable while the migration is rolled out.
    """
    from . import models  # noqa: F401 - ensure model tables are registered for CLI/migration callers
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    statements = []
    user_columns = {item["name"] for item in inspector.get_columns("users")}
    session_columns = {item["name"] for item in inspector.get_columns("sessions")}
    cat_columns = {item["name"] for item in inspector.get_columns("cats")}
    community_columns = {item["name"] for item in inspector.get_columns("communities")}
    if "username" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN username VARCHAR(80)")
    if "password_hash" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
    if "revoked_at" not in session_columns:
        statements.append("ALTER TABLE sessions ADD COLUMN revoked_at DATETIME")
    if "latitude" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN latitude FLOAT")
    if "longitude" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN longitude FLOAT")
    if "photo_asset_id" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN photo_asset_id VARCHAR(32)")
    if "idempotency_key" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN idempotency_key VARCHAR(64)")
    if "version" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
    if "normalized_name" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN normalized_name VARCHAR(120) NOT NULL DEFAULT ''")
    if "review_note" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN review_note TEXT NOT NULL DEFAULT ''")
    if "merged_into_id" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN merged_into_id VARCHAR(32)")
    if "version" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    from .community_rules import normalize_community_name
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id, name FROM communities WHERE normalized_name = '' OR normalized_name IS NULL")).mappings()
        for row in rows:
            try:
                normalized_name = normalize_community_name(row["name"])
            except ValueError:
                normalized_name = "community-" + row["id"]
            connection.execute(
                text("UPDATE communities SET normalized_name = :normalized_name WHERE id = :id"),
                {"normalized_name": normalized_name, "id": row["id"]},
            )
        connection.execute(text("UPDATE communities SET version = 1 WHERE version IS NULL OR version < 1"))
        connection.execute(text("UPDATE cats SET version = 1 WHERE version IS NULL OR version < 1"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communities_normalized_name ON communities (normalized_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communities_merged_into_id ON communities (merged_into_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_cats_actor_idempotency ON cats (created_by, idempotency_key)"))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS fk_communities_merged_into_id_insert
            BEFORE INSERT ON communities
            WHEN NEW.merged_into_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM communities WHERE id = NEW.merged_into_id)
            BEGIN SELECT RAISE(ABORT, 'merged community target does not exist'); END
        """))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS fk_communities_merged_into_id_update
            BEFORE UPDATE OF merged_into_id ON communities
            WHEN NEW.merged_into_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM communities WHERE id = NEW.merged_into_id)
            BEGIN SELECT RAISE(ABORT, 'merged community target does not exist'); END
        """))
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_communities_live_location_name
            ON communities (city, district, normalized_name)
            WHERE status NOT IN ('MERGED','REJECTED','ARCHIVED','HIDDEN')
        """))
