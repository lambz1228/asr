"""对象存储抽象：Local（开发）与 S3 / MinIO（生产）可插拔。

生产环境配置 S3_ENDPOINT / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY 即可切换到
S3 兼容对象存储（AWS S3、阿里云 OSS、腾讯云 COS、MinIO 等）。
"""
import asyncio
import os

from .config import settings


class LocalStorage:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, key: str) -> str:
        # 防目录穿越：解析后必须仍在 root 内
        base = os.path.abspath(self.root)
        full = os.path.abspath(os.path.join(base, key))
        if not (full == base or full.startswith(base + os.sep)):
            raise ValueError("invalid key")
        return full

    async def save(self, key: str, data: bytes) -> str:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def _write() -> None:
            with open(path, "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write)
        return key

    async def read(self, key: str) -> bytes:
        path = self._path(key)

        def _read() -> bytes:
            with open(path, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read)

    async def url(self, key: str) -> str:
        return f"/files/{key}"


class S3Storage:
    def __init__(self):
        import aioboto3  # 延迟导入，本地开发无需安装

        self.session = aioboto3.Session()
        self.bucket = settings.s3_bucket
        self._client_kwargs = dict(
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    async def save(self, key: str, data: bytes) -> str:
        async with self.session.client("s3", **self._client_kwargs) as client:
            await client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    async def read(self, key: str) -> bytes:
        async with self.session.client("s3", **self._client_kwargs) as client:
            resp = await client.get_object(Bucket=self.bucket, Key=key)
            return await resp["Body"].read()

    async def url(self, key: str) -> str:
        async with self.session.client("s3", **self._client_kwargs) as client:
            return await client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600
            )


def get_storage():
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.local_storage_path)


# 进程内单例
storage = get_storage()
