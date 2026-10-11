"""依赖注入：数据库会话、当前用户、角色校验、审计日志。"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from .db import SessionLocal
from . import models
from .jwt_utils import verify_token


async def get_db():
    async with SessionLocal() as session:
        yield session


async def get_current_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    try:
        payload = verify_token(authorization[7:])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return {"uid": payload.get("uid")}


async def get_current_principal(
    authorization: str | None = Header(None), db=Depends(get_db)
) -> dict:
    """校验 token 并从库加载用户角色，返回 {uid, role}。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    try:
        payload = verify_token(authorization[7:])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    uid = payload.get("uid")
    user = await db.scalar(select(models.User).where(models.User.user_id == uid))
    if not user:
        raise HTTPException(status_code=403, detail="user not found")
    return {"uid": user.user_id, "role": user.role}


def require_roles(*roles: str):
    """返回依赖工厂：主体角色不在 roles 内则 403。"""

    async def checker(principal=Depends(get_current_principal)) -> dict:
        if principal["role"] not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal

    return checker


require_admin = require_roles("admin")
require_reviewer = require_roles("admin", "reviewer")


async def get_active_consent(
    db, user_id: str, consent_type: str = "voice_sensitive"
) -> models.ConsentRecord | None:
    """返回该用户某类型下最新且未撤回的同意记录；无则 None。"""
    rec = await db.scalar(
        select(models.ConsentRecord)
        .where(
            models.ConsentRecord.user_id == user_id,
            models.ConsentRecord.type == consent_type,
        )
        .order_by(models.ConsentRecord.signed_at.desc())
    )
    if rec and not rec.revoked:
        return rec
    return None


async def require_voice_consent(
    principal=Depends(get_current_principal), db=Depends(get_db)
) -> dict:
    """PIPL 门禁：语音属敏感个人信息，上传前须有单独的、未撤回的 voice_sensitive 同意。"""
    if not await get_active_consent(db, principal["uid"], "voice_sensitive"):
        raise HTTPException(
            status_code=409,
            detail="需先签署单独的语音敏感信息同意书（voice_sensitive）后方可上传",
        )
    return principal


def record_audit(
    db,
    operator_id: str,
    operator_role: str,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        models.AuditLog(
            operator_id=operator_id,
            operator_role=operator_role,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=detail or {},
            ip=ip,
        )
    )
