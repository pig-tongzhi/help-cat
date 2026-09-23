"""Help Cat API 的组装点。

领域路由在 `helpcat/routers/` 下按领域拆分，共享的序列化、分页、图片处理、日期与
距离规则分别在 `serializers` / `pagination` / `media` / `domain` 里，数据库会话和
当前用户走 `dependencies`。这个文件只做三件事：建配置与引擎、装中间件与异常处理、
按领域把 router 挂到 app 上。

`ROUTERS` 的顺序不影响行为：同一方法下不存在「字面量段与路径参数段互相竞争」的
路由对（`tests/test_app_split_contract.py` 守着这一条），OpenAPI 文档与拆分前逐字
一致。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import WechatProvider, current_user_factory
from .config import Settings
from .db import ensure_schema, make_session_factory
from .routers import (
    admin,
    auth_routes,
    cats,
    communities,
    feeding,
    health,
    impact,
    leads,
    media,
    public_profiles,
    reviews,
    tasks,
)

ROUTERS = (
    health,
    impact,
    public_profiles,
    leads,
    auth_routes,
    communities,
    admin,
    cats,
    reviews,
    tasks,
    feeding,
    media,
)


def create_app(database_url=None, storage_root=None, fake_admin_openids=None):
    settings = Settings(database_url=database_url, storage_root=storage_root, fake_admin_openids=fake_admin_openids)
    if settings.database_url.startswith("sqlite:///") and settings.database_url not in {"sqlite:///", "sqlite:///:memory:"}:
        Path(settings.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    engine, session_factory = make_session_factory(settings.database_url)
    ensure_schema(engine)
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Help Cat API", version="1.0.0")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.wechat_provider = WechatProvider(settings)
    app.state.current_user = current_user_factory(session_factory, settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins or ["http://localhost"], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.exception_handler(HTTPException)
    async def api_http_error(_, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    for module in ROUTERS:
        app.include_router(module.router)

    return app


app = create_app()
