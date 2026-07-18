import threading

import pytest

from app.storage.s3_stub import S3StorageAdapter


class FakeS3Error(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}


class FakeBody:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.thread_ids: list[int] = []

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.thread_ids.append(threading.get_ident())
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket, Key):
        self.thread_ids.append(threading.get_ident())
        try:
            return {"Body": FakeBody(self.objects[(Bucket, Key)])}
        except KeyError:
            raise FakeS3Error("NoSuchKey")

    def delete_object(self, *, Bucket, Key):
        self.thread_ids.append(threading.get_ident())
        self.objects.pop((Bucket, Key), None)

    def head_object(self, *, Bucket, Key):
        self.thread_ids.append(threading.get_ident())
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error("404")

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.thread_ids.append(threading.get_ident())
        return f"https://storage.test/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


@pytest.mark.asyncio
async def test_s3_adapter_round_trip_and_presigned_url():
    client = FakeS3Client()
    adapter = S3StorageAdapter(bucket="pocr", client=client)

    assert await adapter.put("documents/a/raw", b"receipt", "image/png") == "s3://pocr/documents/a/raw"
    assert await adapter.exists("documents/a/raw") is True
    assert await adapter.get("documents/a/raw") == b"receipt"
    assert "documents/a/raw" in await adapter.get_presigned_url("documents/a/raw", 60)
    assert await adapter.delete("documents/a/raw") is True
    assert await adapter.exists("documents/a/raw") is False
    assert all(thread_id != threading.get_ident() for thread_id in client.thread_ids)


@pytest.mark.asyncio
async def test_s3_adapter_maps_missing_object_to_file_not_found():
    adapter = S3StorageAdapter(bucket="pocr", client=FakeS3Client())

    with pytest.raises(FileNotFoundError):
        await adapter.get("documents/missing")
