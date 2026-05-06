import json

from mente.executors.bridge_mcp import query_mente_memory
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository


def _build_environment(
    *,
    source: str = "gateway",
    task_type: str = "conversation",
    policy_id: str = "gateway:conversation",
    bridge_tools: list[str] | None = None,
) -> dict[str, str]:
    return {
        "MENTE_TOOL_POLICY_JSON": json.dumps(
            {
                "policy_id": policy_id,
                "source": source,
                "bridge_tools": bridge_tools or ["mente_memory_query"],
            }
        ),
        "MENTE_EXECUTION_CONTEXT_JSON": json.dumps(
            {
                "task_id": "task_1",
                "session_id": "session_1",
                "task_type": task_type,
                "source": source,
                "policy_id": policy_id,
            }
        ),
        "MENTE_MEMORY_READ_TOOL_ENABLED": "1",
    }


def test_query_mente_memory_returns_policy_bounded_results():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
            score=2.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_global",
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="Repository uses uv for Python commands.",
            score=1.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_task_type",
            task_id="task_old_3",
            task_type="conversation",
            source="gateway",
            scope="task_type",
            fact="Task-type memory should stay hidden from gateway reads.",
            score=3.0,
        )
    )

    result = query_mente_memory(
        limit=5,
        repository=repo,
        environment=_build_environment(),
    )

    assert result == {
        "ok": True,
        "policy_id": "gateway:conversation",
        "results": [
            {
                "memory_id": "mem_session",
                "task_id": "task_old_1",
                "scope": "session",
                "fact": "User prefers concise replies.",
                "source": "gateway",
                "task_type": "conversation",
            },
            {
                "memory_id": "mem_global",
                "task_id": "task_old_2",
                "scope": "global",
                "fact": "Repository uses uv for Python commands.",
                "source": "gateway",
                "task_type": "conversation",
            },
        ],
    }


def test_query_mente_memory_honors_requested_scope():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_global",
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="Repository uses uv for Python commands.",
        )
    )

    result = query_mente_memory(
        memory_scope="global",
        limit=5,
        repository=repo,
        environment=_build_environment(),
    )

    assert result == {
        "ok": True,
        "policy_id": "gateway:conversation",
        "results": [
            {
                "memory_id": "mem_global",
                "task_id": "task_old_2",
                "scope": "global",
                "fact": "Repository uses uv for Python commands.",
                "source": "gateway",
                "task_type": "conversation",
            }
        ],
    }


def test_query_mente_memory_excludes_internal_session_summaries_from_explicit_reads():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="session_1",
            task_id="task_old_summary",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact="Session summary: user prefers concise JSON replies.",
            score=3.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="session_1",
            task_id="task_old_session",
            task_type="conversation",
            source="api_server",
            scope="session",
            fact="User prefers concise replies.",
            score=2.0,
        )
    )

    result = query_mente_memory(
        memory_scope="session",
        limit=1,
        repository=repo,
        environment=_build_environment(
            source="api_server",
            policy_id="api_server:conversation",
        ),
    )

    assert result == {
        "ok": True,
        "policy_id": "api_server:conversation",
        "results": [
            {
                "memory_id": "mem_session",
                "task_id": "task_old_session",
                "scope": "session",
                "fact": "User prefers concise replies.",
                "source": "api_server",
                "task_type": "conversation",
            }
        ],
    }


def test_query_mente_memory_fails_closed_for_disallowed_policy():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_cron",
            task_id="task_old",
            task_type="cron",
            source="cron",
            scope="task_type",
            fact="Cron memory.",
        )
    )

    result = query_mente_memory(
        repository=repo,
        environment=_build_environment(
            source="cron",
            task_type="cron",
            policy_id="cron:cron",
        ),
    )

    assert result == {
        "ok": False,
        "error": "memory_read_not_allowed",
        "policy_id": "cron:cron",
        "reason": "policy_disabled",
    }
