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

    async def delete(self, key: str) -> bool:
        """删除对象；不存在返回 False（不抛异常，便于幂等清理）。"""
        path = self._path(key)

        def _rm() -> bool:
            try:
                os.remove(path)
                return True
            except FileNotFoundError:
                return False

        return await asyncio.to_thread(_rm)

    async def list(self, prefix: str) -> list[tuple[str, float]]:
        """列举 prefix 下的对象，返回 [(key, 修改时间戳秒)]，供过期清理判断。"""
        base = os.path.abspath(self.root)

        def _walk() -> list[tuple[str, float]]:
            out: list[tuple[str, float]] = []
            if not os.path.isdir(base):
                return out
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, base).replace(os.sep, "/")
                    if rel.startswith(prefix):
                        out.append((rel, os.path.getmtime(full)))
            return out

        return await asyncio.to_thread(_walk)


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

    async def delete(self, key: str) -> bool:
        async with self.session.client("s3", **self._client_kwargs) as client:
            await client.delete_object(Bucket=self.bucket, Key=key)
        return True

    async def list(self, prefix: str) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        async with self.session.client("s3", **self._client_kwargs) as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []) or []:
                    ts = obj["LastModified"].timestamp() if obj.get("LastModified") else 0.0
                    out.append((obj["Key"], ts))
        return out


def get_storage():
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.local_storage_path)


# 进程内单例
storage = get_storage()
