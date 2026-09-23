"""响应序列化与审计写入。

所有 `*_payload` 都在这里，路由不再各自拼字典 —— 同一个实体在两处返回不同字段
是这个项目早期最容易出现的偏差。
"""

import json
from datetime import timezone

from sqlalchemy import select

from .auth import issue_session
from .errors import error
from .models import AuditLog, Community


def iso_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def cat_payload(cat):
    community_status = cat.community.status if cat.community else None
    return {"id": cat.id, "community_id": cat.community_id, "code": cat.code, "nickname": cat.nickname,
            "living_status": cat.living_status, "health_status": cat.health_status, "location_note": cat.location_note,
            "review_status": cat.review_status, "visibility_status": cat.visibility_status, "created_by": cat.created_by,
            "photo_asset_id": cat.photo_asset_id, "profile_key": cat.profile_key,
            "latitude": cat.latitude, "longitude": cat.longitude,
            "community_name": cat.community.name if cat.community else "",
            "community_street": cat.community.street if cat.community else "",
            "version": cat.version,
            "community_status": community_status,
            "community_review_blocker": None if community_status == "ACTIVE" else "COMMUNITY_" + community_status}


def community_payload(item):
    return {"id": item.id, "city": item.city, "district": item.district, "street": item.street, "name": item.name,
            "status": item.status, "created_by": item.created_by, "review_note": item.review_note,
            "merged_into_id": item.merged_into_id, "version": item.version}


def admin_community_payload(item, linked_count=0, linked_cats=None, merged_into_name=""):
    result = community_payload(item)
    result.update({
        "linked_cat_count": linked_count,
        "linked_cats": linked_cats or [],
        "merged_into_name": merged_into_name,
    })
    return result


def impact_event_payload(item):
    return {
        "id": item.id, "kind": item.kind, "amount": item.amount, "note": item.note,
        "occurred_at": iso_utc(item.occurred_at), "created_by": item.created_by,
        "reversed_at": iso_utc(item.reversed_at),
        "reversed_by": item.reversed_by, "is_qa": item.is_qa,
    }


def media_payload(asset):
    return {"id": asset.id, "object_key": asset.object_key, "content_type": asset.content_type, "byte_size": asset.byte_size}


def auth_payload(db, user, session_days):
    """注册/登录共用的响应体。"""
    token = issue_session(db, user, session_days)
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user.id, "username": user.username, "role": user.role}}


def user_payload(user):
    return {"id": user.id, "username": user.username, "nickname": user.nickname, "role": user.role,
            "status": user.status, "created_at": user.created_at.isoformat()}


def audit(db, actor_id, action, entity_type, entity_id, before=None, after=None):
    db.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                    before_json=json.dumps(before or {}, ensure_ascii=False), after_json=json.dumps(after or {}, ensure_ascii=False)))


def is_qa_label(value):
    return str(value or "").lstrip().startswith("[QA-")


def normalized_idempotency_key(value):
    key = str(value or "").strip()
    if not 8 <= len(key) <= 64 or not all(character.isalnum() or character in "-_.:" for character in key):
        error(422, "invalid_idempotency_key")
    return key


def normalized_profile_key(value):
    key = str(value or "").strip()
    if not 3 <= len(key) <= 64 or not all(character.islower() or character.isdigit() or character == "-" for character in key):
        error(422, "invalid_profile_key")
    if key.startswith("-") or key.endswith("-") or "--" in key:
        error(422, "invalid_profile_key")
    return key


def lead_message_payload(item):
    return {
        "id": item.id,
        "name": item.name,
        "contact_type": item.contact_type,
        "contact": item.contact,
        "message": item.message,
        "source": item.source,
        "status": item.status,
        "admin_note": item.admin_note,
        "created_at": iso_utc(item.created_at),
        "handled_at": iso_utc(item.handled_at),
    }


def task_payload(item, community_name="", claimed_by_username="", evidence_available=False):
    return {
        "id": item.id, "title": item.title, "description": item.description, "community_id": item.community_id,
        "community_name": community_name, "status": item.status, "created_by": item.created_by,
        "claimed_by": item.claimed_by, "claimed_by_username": claimed_by_username,
        "claimed_at": iso_utc(item.claimed_at), "completed_at": iso_utc(item.completed_at),
        "completion_note": item.completion_note, "evidence_asset_id": item.evidence_asset_id,
        "evidence_available": bool(evidence_available or item.evidence_asset_id),
        "cancelled_at": iso_utc(item.cancelled_at), "cancel_reason": item.cancel_reason,
        "created_at": iso_utc(item.created_at),
    }


def feeding_point_payload(item, fed_today=0, fed_by_me=False, last_fed_at=None, community_name="", distance_m=None, needs_feed=None):
    return {
        "id": item.id, "name": item.name, "community_id": item.community_id, "community_name": community_name,
        "location_note": item.location_note, "feeding_time": item.feeding_time,
        "caretaker_note": item.caretaker_note, "status": item.status,
        "latitude": item.latitude, "longitude": item.longitude,
        "fed_today": fed_today, "fed_by_me": fed_by_me, "last_fed_at": iso_utc(last_fed_at),
        "distance_m": distance_m, "needs_feed": not fed_today if needs_feed is None else needs_feed,
    }


def feeding_log_payload(item, point_name=""):
    return {
        "id": item.id, "point_id": item.point_id, "point_name": point_name, "user_id": item.user_id,
        "fed_on": item.fed_on, "fed_at": iso_utc(item.fed_at), "food_note": item.food_note,
        "note": item.note, "photo_asset_id": item.photo_asset_id,
    }


def public_user_label(user):
    """Mask a volunteer's identity in public responses: 张阿姨 -> 张**."""
    name = (user.nickname or "").strip() or (user.username or "").strip()
    if not name:
        return "志愿者"
    return name[0] + "**"


def feeding_shift_payload(item, point_name="", user_label="", is_mine=False):
    return {
        "id": item.id, "point_id": item.point_id, "point_name": point_name,
        "shift_date": item.shift_date, "status": item.status,
        "user_label": user_label, "is_mine": is_mine, "note": item.note,
    }


def cat_event_payload(item):
    return {
        "id": item.id, "cat_id": item.cat_id, "kind": item.kind, "title": item.title,
        "detail": item.detail, "occurred_at": iso_utc(item.occurred_at),
    }


def community_names(db, ids):
    """Resolve the community names shown next to tasks and feeding points."""
    wanted = {value for value in ids if value}
    if not wanted:
        return {}
    rows = db.execute(select(Community.id, Community.name).where(Community.id.in_(wanted))).all()
    return {row[0]: row[1] for row in rows}
