"""健康检查（liveness / readiness）。"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..dependencies import get_db


router = APIRouter()


@router.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "help-cat-api", "version": "1.0.0"}


@router.get("/api/v1/health/ready")
def health_ready(response: Response, db: DbSession = Depends(get_db)):
    """就绪探针：本地探活脚本和外部 uptime 监控打这个地址。

    带上一次真实查询是有意的：进程还活着但数据库被锁死、文件被删或盘满时，
    `/api/v1/health` 依然会回 200，那种降级对外部监控完全不可见。
    """
    try:
        db.execute(select(1))
    except Exception as exc:  # noqa: BLE001 - 探针要把任何失败都翻成 503
        response.status_code = 503
        return {
            "status": "degraded",
            "service": "help-cat-api",
            "database": "error",
            "detail": type(exc).__name__,
        }
    return {"status": "ok", "service": "help-cat-api", "database": "ok"}
