"""Tests for the Mente memory debug API endpoint on the API server adapter."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import (
    APIServerAdapter,
    cors_middleware,
    security_headers_middleware,
)
from mente.memory.models import MemoryRecord


def _make_adapter(api_key: str = "") -> APIServerAdapter:
    extra = {}
    if api_key:
        extra["key"] = api_key
    return APIServerAdapter(PlatformConfig(enabled=True, extra=extra))


def _create_app(adapter: APIServerAdapter) -> web.Application:
    mws = [mw for mw in (cors_middleware, security_headers_middleware) if mw is not None]
    app = web.Application(middlewares=mws)
    app["api_server_adapter"] = adapter
    app.router.add_get("/api/debug/memories", adapter._handle_debug_memories)
    return app


@pytest.fixture
def adapter():
    return _make_adapter()


class TestDebugMemoriesAPI:
    @pytest.mark.asyncio
    async def test_debug_memories_returns_recent_filtered_memories(self, adapter, monkeypatch):
        class _FakeRepo:
            def __init__(self):
                self.closed = False
                self.recent_requests = []
                self.session_requests = []

            def list_recent(self, limit=20, offset=0, source=None, task_type=None, memory_scope=None):
                self.recent_requests.append((limit, offset, source, task_type, memory_scope))
                return [
                    MemoryRecord(
                        memory_id="mem_001",
                        session_id="sess-123",
                        task_id="task-001",
                        task_type="conversation",
                        source="gateway",
                        scope="session",
                        fact="User prefers concise replies.",
                        created_at=1714300000.0,
                        metadata={"promotion_reason": "executor_memory_candidate"},
                    )
                ]

            def list_by_session(self, session_id, limit=20, offset=0, source=None, task_type=None, memory_scope=None):
                self.session_requests.append((session_id, limit, offset, source, task_type, memory_scope))
                return []

            def close(self):
                self.closed = True

        fake_repo = _FakeRepo()
        monkeypatch.setattr(
            "gateway.platforms.api_server.SQLiteMemoryRepository",
            lambda: fake_repo,
            raising=False,
        )

        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get(
                "/api/debug/memories?scope=recent&source=gateway&task_type=conversation&memory_scope=session&limit=1"
            )

            assert resp.status == 200
            data = await resp.json()
            assert data["query"] == {
                "scope": "recent",
                "session_id": None,
                "source": "gateway",
                "task_type": "conversation",
                "memory_scope": "session",
                "limit": 1,
                "offset": 0,
            }
            assert data["count"] == 1
            assert data["pagination"] == {
                "limit": 1,
                "offset": 0,
                "returned": 1,
                "has_more": False,
                "next_offset": None,
                "next_cursor": None,
            }
            assert data["memories"][0]["memory_id"] == "mem_001"
            assert data["memories"][0]["fact"] == "User prefers concise replies."
            assert fake_repo.recent_requests == [(2, 0, "gateway", "conversation", "session")]
            assert fake_repo.session_requests == []
            assert fake_repo.closed is True
