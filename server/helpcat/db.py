from sqlalchemy import create_engine, event, inspect, text
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
    if database_url.startswith("sqlite"):
        # SQLite defaults (journal_mode=delete, no busy_timeout) make readers and
        # writers block each other, so a second worker hits "database is locked".
        # WAL + a bounded busy timeout let concurrent requests wait instead of fail.
        @event.listens_for(engine, "connect")
        def _apply_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")  # no-op on :memory:
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

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
    task_columns = {item["name"] for item in inspector.get_columns("tasks")}
    feeding_point_columns = {item["name"] for item in inspector.get_columns("feeding_points")}
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
    if "is_qa" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN is_qa BOOLEAN NOT NULL DEFAULT 0")
    if "profile_key" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN profile_key VARCHAR(64)")
    if "normalized_name" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN normalized_name VARCHAR(120) NOT NULL DEFAULT ''")
    if "review_note" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN review_note TEXT NOT NULL DEFAULT ''")
    if "merged_into_id" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN merged_into_id VARCHAR(32)")
    if "version" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
    if "is_qa" not in community_columns:
        statements.append("ALTER TABLE communities ADD COLUMN is_qa BOOLEAN NOT NULL DEFAULT 0")
    if "is_qa" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN is_qa BOOLEAN NOT NULL DEFAULT 0")
    if "completed_at" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN completed_at DATETIME")
    if "completion_note" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN completion_note TEXT NOT NULL DEFAULT ''")
    if "evidence_asset_id" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN evidence_asset_id VARCHAR(32)")
    if "cancelled_at" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN cancelled_at DATETIME")
    if "cancel_reason" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''")
    if "latitude" not in feeding_point_columns:
        statements.append("ALTER TABLE feeding_points ADD COLUMN latitude FLOAT")
    if "longitude" not in feeding_point_columns:
        statements.append("ALTER TABLE feeding_points ADD COLUMN longitude FLOAT")
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
        connection.execute(text("UPDATE communities SET is_qa = 1 WHERE name LIKE '[QA-%'"))
        connection.execute(text("UPDATE cats SET is_qa = 1 WHERE nickname LIKE '[QA-%'"))
        connection.execute(text("UPDATE tasks SET is_qa = 1 WHERE title LIKE '[QA-%'"))
        story_rows = connection.execute(text("""
            SELECT id, profile_key FROM cats
            WHERE profile_key = 'story-77'
               OR (profile_key IS NULL AND nickname = '77' AND location_note LIKE '%2025-06-02 相遇%')
            ORDER BY id
        """)).mappings().all()
        if len(story_rows) > 1:
            raise RuntimeError("multiple legacy cats match story-77; reconcile before startup")
        if story_rows and story_rows[0]["profile_key"] is None:
            connection.execute(
                text("UPDATE cats SET profile_key = 'story-77' WHERE id = :id"),
                {"id": story_rows[0]["id"]},
            )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communities_is_qa ON communities (is_qa)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_cats_is_qa ON cats (is_qa)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_is_qa ON tasks (is_qa)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communities_normalized_name ON communities (normalized_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_communities_merged_into_id ON communities (merged_into_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_cats_actor_idempotency ON cats (created_by, idempotency_key)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_cats_profile_key ON cats (profile_key)"))
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
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_feeding_shifts_live_slot
            ON feeding_shifts (point_id, shift_date)
            WHERE status != 'CANCELLED'
        """))
