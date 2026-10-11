"""统一业务信封：{code, message, data}。"""
from typing import Any


def ok(data: Any = None) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def fail(message: str, code: int = 1) -> dict:
    return {"code": code, "message": message, "data": None}
