"""游标分页：`created_at + id` 的复合游标，避免 offset 在大表上的漂移。"""

import base64
from datetime import datetime

from sqlalchemy import and_, or_

from .errors import error


def encode_cursor(item):
    raw = item.created_at.isoformat() + "|" + item.id
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value):
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        created_at, entity_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(created_at), entity_id
    except (ValueError, UnicodeDecodeError):
        error(422, "invalid_cursor")


def paginated_items(db, stmt, model, cursor, limit):
    if cursor:
        created_at, entity_id = decode_cursor(cursor)
        stmt = stmt.where(or_(model.created_at < created_at, and_(model.created_at == created_at, model.id < entity_id)))
    rows = db.scalars(stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return rows, encode_cursor(rows[-1]) if has_more and rows else None
