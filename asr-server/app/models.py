"""ORM 模型。字段设计对齐方案第 5、10.1、10.2 节（版本管理、审计日志、质量标记）。"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    openid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="collector")  # collector | admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConsentRecord(Base):
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    # 同意类型：voice_sensitive（语音属敏感个人信息，需单独同意）/ general 等
    type: Mapped[str] = mapped_column(String(32), default="voice_sensitive", index=True)
    version: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 撤回后标记，撤回即视为该类型同意失效（PIPL 撤回权）
    revoked: Mapped[bool] = mapped_column(default=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskPackage(Base):
    __tablename__ = "task_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    pkg_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    params: Mapped[dict] = mapped_column(JSON)  # {sample_rate, channels, format, ...}
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TextItem(Base):
    __tablename__ = "texts"
    id: Mapped[int] = mapped_column(primary_key=True)
    text_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    pkg_id: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text)
    text_version: Mapped[int] = mapped_column(default=1)


class TaskAssignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    pkg_id: Mapped[str] = mapped_column(String(32), index=True)
    text_id: Mapped[str] = mapped_column(String(32), index=True)
    assignee: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|claimed|recording|uploaded|reviewing|approved|rejected
    version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    assignment_id: Mapped[str] = mapped_column(String(32), index=True)
    upload_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    version: Mapped[int] = mapped_column(default=1)
    raw_key: Mapped[str] = mapped_column(String(256))
    wav_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    real_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    real_channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    real_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)
    transcode_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|skipped|failed
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewLog(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[str] = mapped_column(String(32), index=True)
    reviewer: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(16))  # approve|reject
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[str] = mapped_column(String(32), index=True)
    operator_role: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportJob(Base):
    __tablename__ = "export_jobs"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|failed
    total: Mapped[int] = mapped_column(default=0)
    key: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 完成的 zip 存储 key
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AudioProbe(Base):
    """真机录音参数验证：端侧探针上报 + 服务端 ffprobe 复核的真实参数。

    仅用于「真机录音参数验证」（方案第 3.2 / 12 节），不参与业务链路。
    dev 态接口写入；主机侧带跑脚本据此聚合出验证矩阵。
    """
    __tablename__ = "audio_probes"
    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    reporter: Mapped[str] = mapped_column(String(32), index=True)  # 上报用户
    device: Mapped[str] = mapped_column(String(64), default="")
    wechat_ver: Mapped[str] = mapped_column(String(32), default="")
    # 端侧请求配置
    req_format: Mapped[str] = mapped_column(String(16), default="")
    req_sample_rate: Mapped[int] = mapped_column(Integer, default=0)
    req_channels: Mapped[int] = mapped_column(Integer, default=0)
    # 端侧文件客观量
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    est_bitrate_kbps: Mapped[float] = mapped_column(Float, default=0.0)
    header_guess: Mapped[str] = mapped_column(String(16), default="")  # aac|mp3|unknown
    # 服务端 ffprobe 复核（权威）
    real_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    real_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    real_channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    real_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    decoded: Mapped[bool | None] = mapped_column(nullable=True)  # 是否可解码
    file_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
