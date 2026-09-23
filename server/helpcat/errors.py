"""统一的错误形状：`{"code": ..., "message": ...}`。"""

from fastapi import HTTPException


def error(status, code, message=None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message or code})
