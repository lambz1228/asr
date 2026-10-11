"""极简 HS256 JWT 工具（仅依赖标准库）。生产请替换为 PyJWT + 密钥管理 + Refresh Token。"""
import base64
import hashlib
import hmac
import json
import time

from .config import settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def create_token(payload: dict, exp_seconds: int = 86400 * 7) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(payload)
    body["exp"] = int(time.time()) + exp_seconds
    signing = _b64(json.dumps(header).encode()) + "." + _b64(json.dumps(body).encode())
    sig = hmac.new(settings.jwt_secret.encode(), signing.encode(), hashlib.sha256).digest()
    return signing + "." + _b64(sig)


def verify_token(token: str) -> dict:
    try:
        signing, sig = token.rsplit(".", 1)
        expected = hmac.new(settings.jwt_secret.encode(), signing.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), sig):
            raise ValueError("bad signature")
        _, payload_b64 = signing.split(".")
        payload = json.loads(_b64d(payload_b64))
        if payload.get("exp", 0) < time.time():
            raise ValueError("token expired")
        return payload
    except Exception as e:
        raise ValueError("invalid token") from e
