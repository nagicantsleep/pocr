from __future__ import annotations

import pytest

from app.storage.local import LocalStorageAdapter


@pytest.fixture
def adapter(tmp_path):
    return LocalStorageAdapter(base_path=str(tmp_path / "storage"))


class TestLocalStorageAdapter:
    @pytest.mark.asyncio
    async def test_put_and_get_bytes(self, adapter):
        data = b"hello world"
        await adapter.put("raw/test.txt", data)
        result = await adapter.get("raw/test.txt")
        assert result == data

    @pytest.mark.asyncio
    async def test_delete_and_exists(self, adapter):
        await adapter.put("raw/deleteme.txt", b"content")
        assert await adapter.exists("raw/deleteme.txt") is True

        deleted = await adapter.delete("raw/deleteme.txt")
        assert deleted is True
        assert await adapter.exists("raw/deleteme.txt") is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, adapter):
        assert await adapter.delete("raw/nope.txt") is False

    @pytest.mark.asyncio
    async def test_presigned_url_returns_string(self, adapter):
        await adapter.put("raw/file.txt", b"data")
        url = await adapter.get_presigned_url("raw/file.txt")
        assert isinstance(url, str)
        assert "raw" in url and "file.txt" in url

    @pytest.mark.asyncio
    async def test_put_creates_parent_directories(self, adapter):
        await adapter.put("a/b/c/deep.txt", b"nested")
        result = await adapter.get("a/b/c/deep.txt")
        assert result == b"nested"

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self, adapter):
        with pytest.raises(FileNotFoundError):
            await adapter.get("does/not/exist.txt")

    @pytest.mark.asyncio
    async def test_exists_false_initially(self, adapter):
        assert await adapter.exists("nothing") is False
