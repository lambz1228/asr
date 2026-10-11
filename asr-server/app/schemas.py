"""请求/响应 Pydantic 模型。"""
from pydantic import BaseModel


class LoginPayload(BaseModel):
    code: str = ""


class ConsentPayload(BaseModel):
    version: str = "1.0"
    # 同意类型：voice_sensitive（语音敏感个人信息，需单独同意）/ general
    type: str = "voice_sensitive"
    payload: str | None = None


class ConsentWithdrawPayload(BaseModel):
    # 撤回的同意类型，默认撤回语音敏感信息同意
    type: str = "voice_sensitive"


class ReviewPayload(BaseModel):
    action: str  # approve | reject
    reason: str | None = None


class TaskItem(BaseModel):
    id: str
    text: str
    status: str


class UploadResult(BaseModel):
    status: str
    audioId: str | None = None
    transcode: str | None = None
    qualityFlags: list = []
