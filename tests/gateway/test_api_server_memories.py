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
    app.router.add_post("/v1/chat/completions", adapter._handle_chat_completions)
    app.router.add_get("/api/debug/memories", adapter._handle_debug_memories)
    return app


@pytest.fixture
def adapter():
    return _make_adapter()


@pytest.fixture
def auth_adapter():
    return _make_adapter(api_key="sk-secret")


class TestDebugMemoriesAPI:
    @pytest.mark.asyncio
    async def test_debug_memories_observes_api_server_bridge_memories(self, adapter, monkeypatch, tmp_path):
        task_db_path = tmp_path / "tasks.db"
        memory_db_path = tmp_path / "memory.db"
        monkeypatch.setenv("HERMES_API_SERVER_EXECUTOR", "mente")
        monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
        monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

        def _fake_execute(self, request):
            from mente.task_core.models import ExecutionResult

            return ExecutionResult(
                status="success",
                summary="via mente",
                memory_candidates=["User prefers concise replies."],
            )

        monkeypatch.setattr("mente.integrations.hermes.CodexExecutor.execute", _fake_execute)

        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            chat_resp = await cli.post(
                "/v1/chat/completions",
                json={
                    "model": "hermes-agent",
                    "messages": [{"role": "user", "content": "Remember this preference"}],
                },
            )

            assert chat_resp.status == 200

            resp = await cli.get(
                "/api/debug/memories?scope=recent&source=api_server&task_type=conversation&limit=1"
            )

            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["memories"][0]["source"] == "api_server"
            assert data["memories"][0]["fact"] == "User prefers concise replies."

    @pytest.mark.asyncio
    async def test_debug_memories_lists_api_server_session_memories(self, auth_adapter, monkeypatch, tmp_path):
        task_db_path = tmp_path / "tasks.db"
        memory_db_path = tmp_path / "memory.db"
        monkeypatch.setenv("HERMES_API_SERVER_EXECUTOR", "mente")
        monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
        monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

        def _fake_execute(self, request):
            from mente.task_core.models import ExecutionResult

            if request.user_request == "Remember this preference":
                return ExecutionResult(
                    status="success",
                    summary="first",
                    memory_candidates=["User prefers concise replies."],
                )
            return ExecutionResult(status="success", summary="second")

        monkeypatch.setattr("mente.integrations.hermes.CodexExecutor.execute", _fake_execute)

        app = _create_app(auth_adapter)
        async with TestClient(TestServer(app)) as cli:
            first_resp = await cli.post(
                "/v1/chat/completions",
                headers={
                    "Authorization": "Bearer sk-secret",
                    "X-Hermes-Session-Id": "api-session-1",
                },
                json={
                    "model": "hermes-agent",
                    "messages": [{"role": "user", "content": "Remember this preference"}],
                },
            )
            second_resp = await cli.post(
                "/v1/chat/completions",
                headers={
                    "Authorization": "Bearer sk-secret",
                    "X-Hermes-Session-Id": "api-session-1",
                },
                json={
                    "model": "hermes-agent",
                    "messages": [{"role": "user", "content": "What do I prefer?"}],
                },
            )

            assert first_resp.status == 200
            assert second_resp.status == 200

            resp = await cli.get(
                "/api/debug/memories?scope=session&session_id=api-session-1"
                "&source=api_server&task_type=conversation&memory_scope=session&limit=5",
                headers={"Authorization": "Bearer sk-secret"},
            )

            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["memories"][0]["source"] == "api_server"
            assert data["memories"][0]["scope"] == "session"
            assert data["memories"][0]["session_id"] == "api-session-1"
            assert data["memories"][0]["fact"] == "User prefers concise replies."

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
