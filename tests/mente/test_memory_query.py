from mente.memory.memory_query import parse_http_memory_query


def test_parse_http_memory_query_normalizes_filters():
    query = parse_http_memory_query(
        {
            "scope": "session",
            "session_id": "sess-42",
            "source": "gateway",
            "task_type": "conversation",
            "memory_scope": "session",
            "cursor": "10",
            "limit": "50",
        }
    )
    assert query == {
        "scope": "session",
        "session_id": "sess-42",
        "source": "gateway",
        "task_type": "conversation",
        "memory_scope": "session",
        "limit": 50,
        "offset": 10,
    }
