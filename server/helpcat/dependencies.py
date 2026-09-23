"""依赖注入：数据库会话与当前用户。

会话、配额、限流都在库里，进程内没有状态，所以这里的依赖都是「每请求一份」，
可以安全地跑多 worker。
"""

from typing import Optional

from fastapi import Header, HTTPException, Request

from .auth import current_user_factory


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


def get_current_user(request: Request, authorization: Optional[str] = Header(default=None)):
    """解析 Bearer token，返回 `(user_id, role)`；失败抛 401/403。"""
    current_user = getattr(request.app.state, "current_user", None)
    if current_user is None:
        current_user = current_user_factory(request.app.state.session_factory, request.app.state.settings)
    return current_user(authorization)


def get_optional_user(request: Request, authorization: Optional[str] = Header(default=None)):
    """Public endpoints that behave differently for a signed-in visitor."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return get_current_user(request, authorization)
    except HTTPException:
        return None
