from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from .. import models
from ..deps import get_current_user, get_db, record_audit, get_active_consent, get_current_principal
from ..jwt_utils import create_token
from ..responses import ok
from ..config import settings
from ..models import utcnow

router = APIRouter()


@router.post("/auth/wx-login")
async def wx_login(request: Request, db=Depends(get_db)):
    body = await request.json()
    code = (body or {}).get("code", "")
    role = (body or {}).get("role", "")  # 仅开发态（DEV_MOCK_LOGIN）可用，便于获取不同角色 token

    if settings.dev_mock_login or not settings.wx_appid:
        # 开发态：按 role 选择对应 seed 演示账号
        if role == "admin":
            user_id = "u_admin"
        else:
            user_id = "u_demo"  # 默认普通采集员
    else:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session",
                params={
                    "appid": settings.wx_appid,
                    "secret": settings.wx_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
            if "openid" not in data:
                return {"code": 1, "message": "微信登录失败", "data": None}
            openid = data["openid"]
            user = await db.scalar(select(models.User).where(models.User.openid == openid))
        if not user:
            role = "admin" if openid in settings.bootstrap_admin_openids else "collector"
            user = models.User(openid=openid, role=role)
            db.add(user)
            await db.flush()
        else:
            # 命中引导列表的已存在用户，提升至 admin（仅升级不降级）
            if openid in settings.bootstrap_admin_openids and user.role != "admin":
                user.role = "admin"
        user_id = user.user_id

    token = create_token({"uid": user_id})
    await db.commit()
    return ok({"token": token, "userId": user_id})


@router.get("/auth/me")
async def me(principal=Depends(get_current_principal)):
    """返回当前用户角色，供前端决定可见入口（如审核台仅对 admin/reviewer 开放）。"""
    return ok({"userId": principal["uid"], "role": principal["role"]})


@router.post("/auth/consent")
async def submit_consent(
    request: Request, user=Depends(get_current_user), db=Depends(get_db)
):
    body = await request.json()
    version = (body or {}).get("version", "1.0")
    consent_type = (body or {}).get("type", "voice_sensitive")
    payload = (body or {}).get("payload")
    # PIPL：敏感个人信息需单独、明确的同意；每条同意独立记录，不与其他条款捆绑
    db.add(
        models.ConsentRecord(
            user_id=user["uid"], type=consent_type, version=version, payload=payload
        )
    )
    record_audit(
        db, user["uid"], "collector", "consent", "user", user["uid"],
        {"type": consent_type, "version": version},
    )
    await db.commit()
    return ok({"signed": True, "type": consent_type})


@router.post("/auth/consent/withdraw")
async def withdraw_consent(
    request: Request, user=Depends(get_current_user), db=Depends(get_db)
):
    """撤回同意（PIPL 撤回权）：将该类型下最新一条未撤回的同意标记为已撤回。"""
    body = await request.json()
    consent_type = (body or {}).get("type", "voice_sensitive")
    active = await db.scalar(
        select(models.ConsentRecord)
        .where(
            models.ConsentRecord.user_id == user["uid"],
            models.ConsentRecord.type == consent_type,
            models.ConsentRecord.revoked.is_(False),
        )
        .order_by(models.ConsentRecord.signed_at.desc())
    )
    if not active:
        return ok({"withdrawn": False, "message": "无生效中的该类型同意"})
    active.revoked = True
    active.revoked_at = utcnow()
    record_audit(
        db, user["uid"], "collector", "consent_withdraw", "user", user["uid"],
        {"type": consent_type},
    )
    await db.commit()
    return ok({"withdrawn": True, "type": consent_type})


@router.get("/auth/consent/status")
async def consent_status(user=Depends(get_current_user), db=Depends(get_db)):
    """查询当前用户「语音敏感信息」同意的生效状态，供小程序决定路由。"""
    rec = await get_active_consent(db, user["uid"], "voice_sensitive")
    if rec:
        return ok(
            {
                "signed": True,
                "type": rec.type,
                "version": rec.version,
                "signedAt": rec.signed_at.isoformat() if rec.signed_at else None,
            }
        )
    return ok({"signed": False, "type": "voice_sensitive"})
