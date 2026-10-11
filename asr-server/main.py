from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, validate_settings
from app.db import SessionLocal, init_db
from app.deps import get_current_user
from app.jwt_utils import verify_token
from app.responses import ok
from app.routers import admin, auth, packages, tasks, upload
from app.seed import seed_demo_data
from app.storage import storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_settings()  # prod 下缺失密钥则启动失败
    await init_db()
    if settings.seed_demo:
        async with SessionLocal() as db:
            await seed_demo_data(db)
    # 启动时清理超期导出文件（方案 §6.2）；失败不阻塞启动
    try:
        from app.cleanup import purge_expired_exports

        async with SessionLocal() as db:
            await purge_expired_exports(db)
    except Exception:
        pass
    yield


app = FastAPI(title="ASR Collector API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(packages.router, prefix="/api")

# 开发态验证接口（真机录音参数验证用），仅 ENV=dev 装配，生产不暴露
if settings.env == "dev":
    from app.routers import dev

    app.include_router(dev.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/files/{key:path}")
async def serve_file(
    key: str,
    authorization: str | None = Header(None),
    token: str | None = None,
):
    # 仅本地存储提供预览路由；S3 / MinIO 走签名 URL
    if settings.storage_backend != "local":
        raise HTTPException(404)
    # 允许 Authorization 头或 ?token= 查询参数（音频播放器无法附带自定义头）
    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization[7:]
    elif token:
        raw = token
    if not raw:
        raise HTTPException(status_code=401, detail="missing token")
    try:
        verify_token(raw)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    try:
        data = await storage.read(key)
    except Exception:
        raise HTTPException(404)
    ctype = "application/octet-stream"
    if key.endswith(".wav"):
        ctype = "audio/wav"
    elif key.endswith(".aac"):
        ctype = "audio/aac"
    elif key.endswith(".mp3"):
        ctype = "audio/mpeg"
    elif key.endswith(".m4a"):
        ctype = "audio/mp4"
    return Response(content=data, media_type=ctype)
