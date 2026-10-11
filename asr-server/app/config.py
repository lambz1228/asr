"""运行时配置：全部通过环境变量注入，便于本地 / 容器 / 生产切换。"""
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # 数据库：默认本地 SQLite（开发）；生产改为 postgresql+asyncpg://user:pass@host/db
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./asr.db")

    # 对象存储：local（开发，落到本地目录）| s3（S3 / MinIO 兼容）
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local")
    local_storage_path: str = os.getenv("LOCAL_STORAGE_PATH", "./data")

    s3_endpoint: str | None = os.getenv("S3_ENDPOINT")
    s3_region: str = os.getenv("S3_REGION", "us-east-1")
    s3_bucket: str = os.getenv("S3_BUCKET", "asr-audio")
    s3_access_key: str | None = os.getenv("S3_ACCESS_KEY")
    s3_secret_key: str | None = os.getenv("S3_SECRET_KEY")

    # FFmpeg / FFprobe
    ffmpeg_path: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    ffprobe_path: str = os.getenv("FFPROBE_PATH", "ffprobe")
    ffmpeg_enabled: bool = os.getenv("FFMPEG_ENABLED", "true").lower() == "true"

    # 鉴权
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me")

    # 微信登录：未配置 APPID 时走开发态 mock 登录
    wx_appid: str | None = os.getenv("WX_APPID")
    wx_secret: str | None = os.getenv("WX_SECRET")
    dev_mock_login: bool = os.getenv("DEV_MOCK_LOGIN", "true").lower() == "true"

    # 管理员引导：逗号分隔的 openid 列表，命中者在首次微信登录时自动获得 admin 角色。
    # 生产用于初始化首位管理员；后续角色调整走 /api/admin/users/{id}/role。
    bootstrap_admin_openids: list = field(
        default_factory=lambda: [
            x.strip() for x in os.getenv("BOOTSTRAP_ADMIN_OPENIDS", "").split(",") if x.strip()
        ]
    )

    # 演示数据：开发态自动播种示例任务
    seed_demo: bool = os.getenv("SEED_DEMO", "true").lower() == "true"

    # 运行环境：dev | prod。prod 下强制校验密钥，缺失则启动失败
    env: str = os.getenv("ENV", "dev")


def validate_settings() -> None:
    """生产环境强制校验密钥配置，缺失即用 RuntimeError 快速失败。"""
    if settings.env != "prod":
        return
    problems = []
    if not settings.jwt_secret or settings.jwt_secret == "dev-secret-change-me":
        problems.append("JWT_SECRET 必须为生产级强随机值")
    if not settings.wx_appid or not settings.wx_secret:
        problems.append("必须配置 WX_APPID / WX_SECRET")
    if settings.dev_mock_login:
        problems.append("生产环境必须关闭 DEV_MOCK_LOGIN（置为 false）")
    if not problems:
        return
    raise RuntimeError("生产配置校验失败:\n- " + "\n- ".join(problems))


settings = Settings()
