"""审核动作的共享实现：单条审核与后台批量审核走**同一段代码**。

后台批量通过如果自己再写一遍"改状态 + 升版本 + 写审计"，迟早会和单条路径分叉
（一条加了校验、另一条忘了）。所以这里把动作抽出来：

* 单条接口（`/cats/{id}/review`、`/communities/{id}/review`）直接调用并抛出 HTTP 错误；
* 批量接口逐条调用、把 HTTP 错误翻成"这一条没成功"，不影响其他条目。

批量时每条独立提交，所以一条失败不会带走已经成功的那些。
"""

from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from .models import Cat, Community
from .serializers import audit, cat_payload, community_payload


def approve_cat(db, cat, actor_id: str, expected_version: Optional[int] = None) -> Cat:
    """把一只猫审核通过。前置条件与单条接口一致：小区必须先开放。"""
    if expected_version is not None and expected_version != cat.version:
        raise HTTPException(status_code=409, detail={"code": "stale_cat_version", "message": "stale_cat_version"})
    if cat.community is None or cat.community.status != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "community_not_active", "message": "community_not_active"})
    if cat.review_status == "APPROVED":
        return cat
    before = {"review_status": cat.review_status}
    cat.review_status = "APPROVED"
    cat.version += 1
    audit(db, actor_id, "REVIEW", "cat", cat.id, before, {"review_status": cat.review_status})
    _commit(db, "stale_cat_version")
    return cat


def reject_cat(db, cat, actor_id: str) -> Cat:
    before = {"review_status": cat.review_status}
    cat.review_status = "REJECTED"
    cat.version += 1
    audit(db, actor_id, "REVIEW", "cat", cat.id, before, {"review_status": cat.review_status})
    _commit(db, "stale_cat_version")
    return cat


def approve_community(db, community, actor_id: str, note: str = "", expected_version: Optional[int] = None) -> Community:
    """开放一个待审小区。状态不对就报错，交给调用方决定是中止还是跳过。"""
    if community.status not in {"PENDING_REVIEW", "NEEDS_CHANGES"}:
        raise HTTPException(status_code=409, detail={"code": "community_review_state_invalid", "message": "community_review_state_invalid"})
    if expected_version is not None and expected_version != community.version:
        raise HTTPException(status_code=409, detail={"code": "stale_community_version", "message": "stale_community_version"})
    before = community_payload(community)
    community.status = "ACTIVE"
    community.review_note = (note or "").strip()
    community.reviewed_by = actor_id
    community.version += 1
    audit(db, actor_id, "REVIEW", "community", community.id, before, community_payload(community))
    _commit(db, "stale_community_version")
    return community


def _commit(db, stale_code: str) -> None:
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": stale_code, "message": stale_code})


def _result(item_id: str, status: str, code: str = "", label: str = "") -> Dict[str, str]:
    return {"id": item_id, "status": status, "code": code, "label": label}


def batch_approve(db, actor_id: str, cat_items: List[Dict], community_items: List[Dict],
                  include_communities: bool = True) -> Dict[str, object]:
    """逐条通过；每条独立提交，一条失败不影响其他条目。

    `include_communities=True` 时，如果某只猫挂在待审小区下，会先把那个小区开放 ——
    这是"提交新小区 + 新猫咪"那种一次投稿要连点两次的根源。
    """
    communities: List[Dict[str, str]] = []
    cats: List[Dict[str, str]] = []
    extra_communities: List[Community] = []

    for item in community_items:
        community = db.get(Community, item["id"])
        if community is None:
            communities.append(_result(item["id"], "not_found", "community_not_found"))
            continue
        try:
            approve_community(db, community, actor_id, note=item.get("note", ""), expected_version=item.get("version"))
            communities.append(_result(community.id, "approved", "", community.name))
        except HTTPException as exc:
            communities.append(_result(item["id"], "skipped", exc.detail.get("code", "error"), community.name))

    for item in cat_items:
        cat = db.get(Cat, item["id"])
        if cat is None:
            cats.append(_result(item["id"], "not_found", "cat_not_found"))
            continue
        if include_communities and cat.community is not None and cat.community.status in {"PENDING_REVIEW", "NEEDS_CHANGES"}:
            try:
                approve_community(db, cat.community, actor_id, note="随猫咪档案一并开放")
                extra_communities.append(cat.community)
            except HTTPException as exc:
                cats.append(_result(cat.id, "skipped", exc.detail.get("code", "error"), cat.nickname))
                continue
        try:
            approve_cat(db, cat, actor_id, expected_version=item.get("version"))
            cats.append(_result(cat.id, "approved", "", cat.nickname))
        except HTTPException as exc:
            cats.append(_result(cat.id, "skipped", exc.detail.get("code", "error"), cat.nickname))

    approved = [item for item in cats + communities if item["status"] == "approved"]
    skipped = [item for item in cats + communities if item["status"] != "approved"]
    return {
        "cats": cats,
        "communities": communities,
        "approved_count": len(approved),
        "skipped_count": len(skipped),
        "opened_communities": [{"id": item.id, "name": item.name} for item in extra_communities],
    }


def pending_review_counts(db) -> Dict[str, int]:
    cats = db.scalars(select(Cat.id).where(Cat.review_status == "PENDING_REVIEW")).all()
    communities = db.scalars(
        select(Community.id).where(Community.status.in_(["PENDING_REVIEW", "NEEDS_CHANGES"]))
    ).all()
    return {"cats": len(cats), "communities": len(communities)}
