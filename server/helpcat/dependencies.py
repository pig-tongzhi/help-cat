"""依赖注入：数据库会话与当前用户。

会话、配额、限流都在库里，进程内没有状态，所以这里的依赖都是「每请求一份」，
可以安全地跑多 worker。
"""

from typing import Annotated, Optional

from fastapi import Cookie, Header, HTTPException, Request

from .auth import current_user_factory


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


def get_current_user(
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
    helpcat_session: Annotated[Optional[str], Cookie()] = None,
):
    """解析 Bearer token（或 HttpOnly Cookie），返回 `(user_id, role)`；失败抛 401/403。

    这里必须显式把 Cookie 传进闭包：闭包是被**直接调用**的，FastAPI 不会替它解析参数
    （踩过：只加闭包的 Cookie 参数，请求里带了 Cookie 也依然 401）。
    """
    current_user = getattr(request.app.state, "current_user", None)
    if current_user is None:
        current_user = current_user_factory(request.app.state.session_factory, request.app.state.settings)
    return current_user(authorization, helpcat_session)


def get_optional_user(request: Request, authorization: Annotated[Optional[str], Header()] = None,
                      helpcat_session: Annotated[Optional[str], Cookie()] = None):
    """Public endpoints that behave differently for a signed-in visitor."""
    if not authorization and not helpcat_session:
        return None
    try:
        return get_current_user(request, authorization, helpcat_session)
    except HTTPException:
        return None
