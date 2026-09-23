"""公开可见性的完整矩阵。

`test_public_qa_isolation.py` 管的是「QA 数据不进公开列表」；这个文件管另一件事：
**任何没有同时满足「已审核 + 已发布」的档案都不能被普通用户看到**，不管它是 QA 数据
还是真实数据。HIDDEN 是一个合法状态（档案先审核通过、但管理员暂时不想展示），
线上曾经出现过「已公开但隐藏」的档案 —— 那类档案一旦漏出去，就是隐私与内容事故。

每个用例都用真实 ASGI 请求，不 mock 过滤器。
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from server.helpcat.app import create_app
from server.helpcat.db import ensure_schema, make_session_factory
from server.helpcat.models import Cat, Community, User


class CatVisibilityMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        app = create_app("sqlite://", storage_root=self.root)
        self.session_factory = app.state.session_factory
        self.app = app
        self.community_id = "community-visible"
        with self.session_factory() as db:
            db.add(Community(
                id=self.community_id, city="杭州市", district="富阳区", street="银湖街道",
                name="银湖花园", normalized_name="银湖花园", status="ACTIVE", created_by="u-admin",
            ))
            db.add(User(id="u-admin", openid="openid-admin", role="SUPER_ADMIN", nickname="管理员"))
            # 五种状态各来一只：只有最后一只该被普通用户看到。
            for index, (review, visibility, qa) in enumerate((
                ("PENDING_REVIEW", "ACTIVE", False),   # 还没审核
                ("REJECTED", "ACTIVE", False),         # 审核未通过
                ("APPROVED", "HIDDEN", False),         # 审核通过但管理员隐藏
                ("APPROVED", "ARCHIVED", False),       # 已归档
                ("APPROVED", "ACTIVE", True),          # QA 数据
                ("APPROVED", "ACTIVE", False),         # 正常公开
            )):
                db.add(Cat(
                    id="cat-%d" % index, community_id=self.community_id, code="HC-TEST%d" % index,
                    nickname="档案%d" % index, living_status="", health_status="UNKNOWN",
                    location_note="绿化带", review_status=review, visibility_status=visibility,
                    is_qa=qa, created_by="u-admin",
                ))
            db.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def public_list(self):
        from httpx import AsyncClient, ASGITransport

        async def run():
            transport = ASGITransport(app=self.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/cats", params={"limit": 50})
                return response.status_code, response.json()

        return asyncio.run(run())

    def test_only_approved_and_active_cats_reach_the_public_list(self):
        status, body = self.public_list()
        self.assertEqual(200, status)
        nicknames = sorted(item["nickname"] for item in body["items"])
        self.assertEqual(["档案5"], nicknames, "公开列表只应有「已审核 + 已发布 + 非 QA」的那一只")

    def test_hidden_cat_is_not_reachable_by_direct_id_lookups(self):
        """公开列表过滤掉了不够，按 id 直查也不能漏。"""
        from httpx import AsyncClient, ASGITransport

        async def run():
            transport = ASGITransport(app=self.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                results = {}
                for cat_id in ("cat-0", "cat-1", "cat-2", "cat-3", "cat-4"):
                    response = await client.get("/api/v1/cats/%s/events" % cat_id)
                    results[cat_id] = response.status_code
                return results

        # 时间线接口对未知/不可见档案应当 404，而不是把档案内容吐出来。
        for cat_id, status in asyncio.run(run()).items():
            self.assertIn(status, (403, 404), "%s 的公开接口返回了 %s" % (cat_id, status))

    def test_admin_still_sees_every_state(self):
        with self.session_factory() as db:
            from server.helpcat.auth import hash_password
            db.add(User(id="u-ops", openid="local:ops", username="ops",
                        password_hash=hash_password("ops-password"), role="ADMIN", nickname="ops"))
            db.commit()

        from httpx import AsyncClient, ASGITransport

        async def admin_list():
            transport = ASGITransport(app=self.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                anonymous = await client.get("/api/v1/cats", params={"limit": 50})
                token = (await client.post("/api/v1/auth/login", json={"username": "ops", "password": "ops-password"})).json()["access_token"]
                as_admin = await client.get(
                    "/api/v1/cats", params={"limit": 50}, headers={"Authorization": "Bearer " + token}
                )
                return anonymous.json(), as_admin.json()

        anonymous, as_admin = asyncio.run(admin_list())
        self.assertEqual(1, len(anonymous["items"]))
        self.assertEqual(6, len(as_admin["items"]), "管理员必须能看到全部状态")


if __name__ == "__main__":
    unittest.main()
