"""The hand-written schema repairs that predate Alembic.

The pilot database was built by ``Base.metadata.create_all`` plus a list of raw
``ALTER TABLE`` statements inside ``ensure_schema``.  That list made a second
schema source of truth: a database built only from the migrations never got
those columns, and nothing failed until a request touched one.

This module is now the only place those repairs are written down.  Migration
``011_bootstrap_parity`` and the runtime bootstrap both replay exactly this
list, so an empty database, a legacy pilot database, and the production
database all converge on the same shape.
"""

from sqlalchemy import inspect, text

# Every column that was ever bolted onto a deployed table by hand.
# (table, column, DDL type)
LEGACY_COLUMNS = (
    ("users", "username", "VARCHAR(80)"),
    ("users", "password_hash", "VARCHAR(255)"),
    ("sessions", "revoked_at", "DATETIME"),
    ("cats", "latitude", "FLOAT"),
    ("cats", "longitude", "FLOAT"),
    ("cats", "photo_asset_id", "VARCHAR(32)"),
    ("cats", "idempotency_key", "VARCHAR(64)"),
    ("cats", "version", "INTEGER NOT NULL DEFAULT 1"),
    ("cats", "is_qa", "BOOLEAN NOT NULL DEFAULT 0"),
    ("cats", "profile_key", "VARCHAR(64)"),
    ("communities", "normalized_name", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("communities", "review_note", "TEXT NOT NULL DEFAULT ''"),
    ("communities", "merged_into_id", "VARCHAR(32)"),
    ("communities", "version", "INTEGER NOT NULL DEFAULT 1"),
    ("communities", "is_qa", "BOOLEAN NOT NULL DEFAULT 0"),
    ("tasks", "is_qa", "BOOLEAN NOT NULL DEFAULT 0"),
    ("tasks", "completed_at", "DATETIME"),
    ("tasks", "completion_note", "TEXT NOT NULL DEFAULT ''"),
    ("tasks", "evidence_asset_id", "VARCHAR(32)"),
    ("tasks", "cancelled_at", "DATETIME"),
    ("tasks", "cancel_reason", "TEXT NOT NULL DEFAULT ''"),
    ("feeding_points", "latitude", "FLOAT"),
    ("feeding_points", "longitude", "FLOAT"),
)

# Indexes and triggers a migrated database must have even when it was built by
# an older release.  ``IF NOT EXISTS`` keeps the replay idempotent.
LEGACY_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_communities_is_qa ON communities (is_qa)",
    "CREATE INDEX IF NOT EXISTS ix_cats_is_qa ON cats (is_qa)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_is_qa ON tasks (is_qa)",
    "CREATE INDEX IF NOT EXISTS ix_communities_normalized_name ON communities (normalized_name)",
    "CREATE INDEX IF NOT EXISTS ix_communities_merged_into_id ON communities (merged_into_id)",
    # Revision 006 forgot this one; the model declares it, so an existing
    # database reaches parity through this replay.
    "CREATE INDEX IF NOT EXISTS ix_impact_events_created_by ON impact_events (created_by)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cats_actor_idempotency ON cats (created_by, idempotency_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cats_profile_key ON cats (profile_key)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_communities_live_location_name
    ON communities (city, district, normalized_name)
    WHERE status NOT IN ('MERGED','REJECTED','ARCHIVED','HIDDEN')
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_feeding_shifts_live_slot
    ON feeding_shifts (point_id, shift_date)
    WHERE status != 'CANCELLED'
    """,
)

LEGACY_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS fk_communities_merged_into_id_insert
    BEFORE INSERT ON communities
    WHEN NEW.merged_into_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM communities WHERE id = NEW.merged_into_id)
    BEGIN SELECT RAISE(ABORT, 'merged community target does not exist'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fk_communities_merged_into_id_update
    BEFORE UPDATE OF merged_into_id ON communities
    WHEN NEW.merged_into_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM communities WHERE id = NEW.merged_into_id)
    BEGIN SELECT RAISE(ABORT, 'merged community target does not exist'); END
    """,
)

# Row-level repairs that shipped alongside the columns above.
LEGACY_DATA_REPAIRS = (
    "UPDATE communities SET version = 1 WHERE version IS NULL OR version < 1",
    "UPDATE cats SET version = 1 WHERE version IS NULL OR version < 1",
    "UPDATE communities SET is_qa = 1 WHERE name LIKE '[QA-%'",
    "UPDATE cats SET is_qa = 1 WHERE nickname LIKE '[QA-%'",
    "UPDATE tasks SET is_qa = 1 WHERE title LIKE '[QA-%'",
)


def missing_columns(connection):
    """Return the ``LEGACY_COLUMNS`` entries the database does not have yet."""
    inspector = inspect(connection)
    missing = []
    for table, column, ddl in LEGACY_COLUMNS:
        if not inspector.has_table(table):
            continue
        if column in {item["name"] for item in inspector.get_columns(table)}:
            continue
        missing.append((table, column, ddl))
    return missing


def _backfill_normalized_names(connection):
    from .community_rules import normalize_community_name

    rows = connection.execute(
        text("SELECT id, name FROM communities WHERE normalized_name = '' OR normalized_name IS NULL")
    ).mappings().all()
    for row in rows:
        try:
            normalized_name = normalize_community_name(row["name"])
        except ValueError:
            normalized_name = "community-" + row["id"]
        connection.execute(
            text("UPDATE communities SET normalized_name = :normalized_name WHERE id = :id"),
            {"normalized_name": normalized_name, "id": row["id"]},
        )


def _backfill_story_77(connection):
    story_rows = connection.execute(
        text(
            """
            SELECT id, profile_key FROM cats
            WHERE profile_key = 'story-77'
               OR (profile_key IS NULL AND nickname = '77' AND location_note LIKE '%2025-06-02 相遇%')
            ORDER BY id
            """
        )
    ).mappings().all()
    if len(story_rows) > 1:
        raise RuntimeError("multiple legacy cats match story-77; reconcile before startup")
    if story_rows and story_rows[0]["profile_key"] is None:
        connection.execute(
            text("UPDATE cats SET profile_key = 'story-77' WHERE id = :id"),
            {"id": story_rows[0]["id"]},
        )


def apply_legacy_upgrades(connection):
    """Bring an existing database up to the shape the current models expect."""
    for table, column, ddl in missing_columns(connection):
        connection.execute(text("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl)))
    for statement in LEGACY_INDEXES:
        connection.execute(text(statement))
    for statement in LEGACY_TRIGGERS:
        connection.execute(text(statement))
    _backfill_normalized_names(connection)
    for statement in LEGACY_DATA_REPAIRS:
        connection.execute(text(statement))
    _backfill_story_77(connection)
