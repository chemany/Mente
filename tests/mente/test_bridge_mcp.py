import json
from pathlib import Path

from mente.executors.bridge_mcp import (
    augment_runtime_config_for_bridge_tools,
    query_mente_memory,
    save_mente_memory,
    publish_wechat_draft,
)
from mente.executors.mcp_server import create_mcp_server
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.executors.runtime_config import RuntimeConfig
from mente.task_core.models import ExecutionRequest


def _bridge_env(
    *,
    bridge_tools: list[str],
    task_id: str = "task_1",
    session_id: str = "session_1",
    task_type: str = "conversation",
    source: str = "gateway",
    policy_id: str = "gateway:conversation",
    enable_read: bool = False,
    enable_write: bool = False,
) -> dict[str, str]:
    environment = {
        "MENTE_TOOL_POLICY_JSON": json.dumps(
            {
                "policy_id": policy_id,
                "source": source,
                "bridge_tools": bridge_tools,
            }
        ),
        "MENTE_EXECUTION_CONTEXT_JSON": json.dumps(
            {
                "task_id": task_id,
                "session_id": session_id,
                "task_type": task_type,
                "source": source,
                "policy_id": policy_id,
            }
        ),
    }
    if enable_read:
        environment["MENTE_MEMORY_READ_TOOL_ENABLED"] = "1"
    if enable_write:
        environment["MENTE_MEMORY_WRITE_TOOL_ENABLED"] = "1"
    return environment


def test_augment_runtime_config_injects_mente_mcp_server_for_supported_bridge_tools(
    monkeypatch,
    tmp_path,
):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-private"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Publish this article to WeChat drafts.",
        workspace=str(tmp_path),
        tool_policy={
            "bridge_tools": ["mente_wechat_publish_draft"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)
    overrides = augmented.to_codex_overrides()

    assert 'model="gpt-5.5"' in overrides
    assert any(item.startswith('mcp_servers.mente.command=') for item in overrides)
    assert 'mcp_servers.mente.args=["-m", "mente.executors.mcp_server"]' in overrides
    assert f'mcp_servers.mente.cwd="{Path.cwd()}"' in overrides
    assert 'mcp_servers.mente.default_tools_approval_mode="approve"' in overrides
    assert 'mcp_servers.mente.enabled_tools=["mente_wechat_publish_draft"]' in overrides
    assert augmented.subprocess_env["MENTE_CODEX_API_KEY"] == "sk-private"
    assert augmented.subprocess_env["MENTE_HOME"] == str(mente_home)
    assert "MENTE_HOST_HOME" in augmented.subprocess_env


def test_augment_runtime_config_leaves_unmapped_bridge_tools_unchanged(tmp_path):
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user.",
        workspace=str(tmp_path),
        tool_policy={
            "bridge_tools": ["mente_task_lookup"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)

    assert augmented == runtime_config


def test_augment_runtime_config_injects_memory_query_when_flag_is_on_by_default(
    tmp_path,
):
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Recall any prior preferences.",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "bridge_tools": ["mente_memory_query"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)
    overrides = augmented.to_codex_overrides()

    assert 'mcp_servers.mente.enabled_tools=["mente_memory_query"]' in overrides


def test_augment_runtime_config_does_not_inject_memory_query_when_flag_is_explicitly_disabled(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MENTE_MEMORY_READ_TOOL_ENABLED", "0")
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Recall any prior preferences.",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "bridge_tools": ["mente_memory_query"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)

    assert augmented == runtime_config


def test_augment_runtime_config_injects_mente_mcp_server_for_memory_query_tool(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MENTE_MEMORY_READ_TOOL_ENABLED", "1")
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Recall any prior preferences.",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "bridge_tools": ["mente_memory_query"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)
    overrides = augmented.to_codex_overrides()

    assert 'mcp_servers.mente.args=["-m", "mente.executors.mcp_server"]' in overrides
    assert 'mcp_servers.mente.enabled_tools=["mente_memory_query"]' in overrides
    assert json.loads(augmented.subprocess_env["MENTE_TOOL_POLICY_JSON"]) == {
        "policy_id": "gateway:conversation",
        "source": "gateway",
        "bridge_tools": ["mente_memory_query"],
    }
    assert json.loads(augmented.subprocess_env["MENTE_EXECUTION_CONTEXT_JSON"]) == {
        "task_id": "task_1",
        "session_id": "session_1",
        "task_type": "conversation",
        "source": "gateway",
        "policy_id": "gateway:conversation",
    }


def test_augment_runtime_config_does_not_inject_memory_save_when_flag_is_off_by_default(
    tmp_path,
):
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Remember the user's standing preference.",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "bridge_tools": ["mente_memory_save"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)

    assert augmented == runtime_config


def test_augment_runtime_config_injects_mente_mcp_server_for_memory_save_tool(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MENTE_MEMORY_WRITE_TOOL_ENABLED", "1")
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Remember the user's standing preference.",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "bridge_tools": ["mente_memory_save"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)
    overrides = augmented.to_codex_overrides()

    assert 'mcp_servers.mente.enabled_tools=["mente_memory_save"]' in overrides
    assert json.loads(augmented.subprocess_env["MENTE_TOOL_POLICY_JSON"]) == {
        "policy_id": "gateway:conversation",
        "source": "gateway",
        "bridge_tools": ["mente_memory_save"],
    }


def test_augment_runtime_config_normalizes_legacy_memory_append_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_MEMORY_WRITE_TOOL_ENABLED", "1")
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-runtime-home",
        codex_config={"model": "gpt-5.5"},
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Remember the user's standing preference.",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "bridge_tools": ["mente_memory_append"],
        },
    )

    augmented = augment_runtime_config_for_bridge_tools(runtime_config, request)
    overrides = augmented.to_codex_overrides()

    assert 'mcp_servers.mente.enabled_tools=["mente_memory_save"]' in overrides


def test_create_mcp_server_registers_memory_query_tool(monkeypatch):
    registered_tools = {}

    class FakeMCP:
        def __init__(self, name, instructions):
            self.name = name
            self.instructions = instructions

        def tool(self):
            def decorator(func):
                registered_tools[func.__name__] = func
                return func

            return decorator

    monkeypatch.setattr("mente.executors.mcp_server.FastMCP", FakeMCP)
    monkeypatch.setattr("mente.executors.mcp_server._MCP_SERVER_AVAILABLE", True)

    server = create_mcp_server()

    assert server.name == "mente"
    assert set(registered_tools) >= {
        "mente_memory_query",
        "mente_memory_save",
        "mente_wechat_publish_draft",
    }


def test_save_mente_memory_persists_gateway_conversation_write_with_attribution():
    repo = InMemoryMemoryRepository()

    result = save_mente_memory(
        fact="  User prefers JSON-first replies.  \n\n",
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_save"],
            enable_write=True,
        ),
    )

    assert result == {
        "ok": True,
        "policy_id": "gateway:conversation",
        "memory_id": result["memory_id"],
        "scope": "session",
        "fact": "User prefers JSON-first replies.",
        "metadata": {
            "promotion_reason": "explicit_memory_write",
            "tool_name": "mente_memory_save",
            "write_origin": "explicit_memory_write",
            "task_id": "task_1",
            "session_id": "session_1",
            "source": "gateway",
            "task_type": "conversation",
        },
    }
    assert result["memory_id"].startswith("task_1:explicit_memory:")
    persisted = repo.get(result["memory_id"])
    assert persisted is not None
    assert persisted.scope == "session"
    assert persisted.session_id == "session_1"
    assert persisted.fact == "User prefers JSON-first replies."
    assert persisted.metadata == result["metadata"]


def test_save_mente_memory_accepts_legacy_memory_append_tool_alias():
    repo = InMemoryMemoryRepository()

    result = save_mente_memory(
        fact="Persist this through the legacy alias.",
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_append"],
            enable_write=True,
        ),
    )

    assert result["ok"] is True
    assert result["metadata"]["tool_name"] == "mente_memory_save"
    assert repo.get(result["memory_id"]) is not None


def test_save_mente_memory_denies_disallowed_scope_override():
    repo = InMemoryMemoryRepository()

    result = save_mente_memory(
        fact="Persist this as task-type memory.",
        memory_scope="task_type",
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_save"],
            enable_write=True,
        ),
    )

    assert result == {
        "ok": False,
        "error": "memory_write_not_allowed",
        "policy_id": "gateway:conversation",
        "reason": "scope_not_allowed:task_type",
    }
    assert repo.list_recent() == []


def test_save_mente_memory_denies_non_conversation_write_when_policy_disabled():
    repo = InMemoryMemoryRepository()

    result = save_mente_memory(
        fact="Cron reminder.",
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_save"],
            task_type="cron",
            source="cron",
            policy_id="cron:cron",
            enable_write=True,
        ),
    )

    assert result == {
        "ok": False,
        "error": "memory_write_not_allowed",
        "policy_id": "cron:cron",
        "reason": "policy_disabled",
    }
    assert repo.list_recent() == []


def test_save_mente_memory_denies_when_write_tool_flag_is_off_by_default():
    repo = InMemoryMemoryRepository()

    result = save_mente_memory(
        fact="Do not persist this while the operator flag is off.",
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_save"],
        ),
    )

    assert result == {
        "ok": False,
        "error": "memory_write_not_allowed",
        "policy_id": "gateway:conversation",
        "reason": "disabled",
    }
    assert repo.list_recent() == []



def test_query_mente_memory_returns_structured_denial_when_scope_is_not_allowed():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_task_type",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="task_type",
            fact="Project prefers changelog fragments in PRs.",
        )
    )

    result = query_mente_memory(
        memory_scope="task_type",
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_query"],
            enable_read=True,
        ),
    )

    assert result == {
        "ok": False,
        "error": "memory_read_not_allowed",
        "policy_id": "gateway:conversation",
        "reason": "scope_not_allowed:task_type",
    }


def test_query_mente_memory_returns_source_filtered_success_for_gateway_conversation():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Gateway session memory.",
            score=1.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_other_session",
            session_id="session_1",
            task_id="task_old_2",
            task_type="conversation",
            source="api_server",
            scope="session",
            fact="Should be excluded because the source does not match.",
            score=100.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_global_top",
            task_id="task_old_3",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="Gateway global memory.",
            score=5.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_global_lower",
            task_id="task_old_4",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="Lower-priority global memory.",
            score=3.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_other_global",
            task_id="task_old_5",
            task_type="conversation",
            source="cron",
            scope="global",
            fact="Should be excluded because the source does not match.",
            score=50.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_task_type",
            task_id="task_old_6",
            task_type="conversation",
            source="gateway",
            scope="task_type",
            fact="Should be excluded because gateway reads do not allow task_type scope.",
            score=200.0,
        )
    )

    result = query_mente_memory(
        limit=2,
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_query"],
            enable_read=True,
        ),
    )

    assert result == {
        "ok": True,
        "policy_id": "gateway:conversation",
        "results": [
            {
                "memory_id": "mem_gateway_session",
                "task_id": "task_old_1",
                "scope": "session",
                "fact": "Gateway session memory.",
                "source": "gateway",
                "task_type": "conversation",
            },
            {
                "memory_id": "mem_gateway_global_top",
                "task_id": "task_old_3",
                "scope": "global",
                "fact": "Gateway global memory.",
                "source": "gateway",
                "task_type": "conversation",
            },
        ],
    }


def test_query_mente_memory_allows_reads_when_flag_is_on_by_default():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Gateway session memory.",
            score=1.0,
        )
    )

    result = query_mente_memory(
        repository=repo,
        environment=_bridge_env(
            bridge_tools=["mente_memory_query"],
        ),
    )

    assert result == {
        "ok": True,
        "policy_id": "gateway:conversation",
        "results": [
            {
                "memory_id": "mem_gateway_session",
                "task_id": "task_old_1",
                "scope": "session",
                "fact": "Gateway session memory.",
                "source": "gateway",
                "task_type": "conversation",
            }
        ],
    }


def test_query_mente_memory_denies_when_read_tool_flag_is_explicitly_disabled():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Gateway session memory.",
            score=1.0,
        )
    )

    environment = _bridge_env(
        bridge_tools=["mente_memory_query"],
    )
    environment["MENTE_MEMORY_READ_TOOL_ENABLED"] = "0"

    result = query_mente_memory(
        repository=repo,
        environment=environment,
    )

    assert result == {
        "ok": False,
        "error": "memory_read_not_allowed",
        "policy_id": "gateway:conversation",
        "reason": "disabled",
    }


def test_publish_wechat_draft_invokes_host_publish_script(tmp_path):
    skill_root = tmp_path / "skills" / "media" / "wechat-publisher"
    publish_script = skill_root / "scripts" / "publisher" / "publish.js"
    publish_script.parent.mkdir(parents=True, exist_ok=True)
    publish_script.write_text("// stub", encoding="utf-8")
    article_path = tmp_path / "article.md"
    article_path.write_text("# Draft", encoding="utf-8")
    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = "published"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Completed()

    result = publish_wechat_draft(
        article_path=str(article_path),
        skill_root=skill_root,
        subprocess_run=fake_run,
    )

    assert result["ok"] is True
    assert result["article_path"] == str(article_path)
    assert captured["command"] == [
        "node",
        str(publish_script),
        str(article_path),
        "lapis",
        "solarized-light",
    ]
    assert captured["kwargs"]["cwd"] == str(skill_root)
    assert captured["kwargs"]["env"]["HOME"]


def test_publish_wechat_draft_finalizes_source_markdown_via_create_article(tmp_path):
    skill_root = tmp_path / "skills" / "media" / "wechat-publisher"
    create_script = skill_root / "scripts" / "publisher" / "create-article.js"
    create_script.parent.mkdir(parents=True, exist_ok=True)
    create_script.write_text("// stub", encoding="utf-8")
    source_path = tmp_path / "source.md"
    source_path.write_text(
        "---\n"
        "title: 从 source 收口发布\n"
        "---\n\n"
        "# Draft\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = "published from source"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Completed()

    result = publish_wechat_draft(
        article_path=str(source_path),
        skill_root=skill_root,
        subprocess_run=fake_run,
    )

    assert result["ok"] is True
    assert result["article_path"] == str(source_path)
    assert result["source_path"] == str(source_path)
    assert result["finalize_mode"] == "source_markdown"
    assert captured["command"] == [
        "node",
        str(create_script),
        "从 source 收口发布",
        "--from",
        str(source_path),
        "--publish",
    ]
    assert captured["kwargs"]["cwd"] == str(skill_root)
    assert captured["kwargs"]["env"]["HOME"]


def test_publish_wechat_draft_returns_structured_failure_for_missing_article(tmp_path):
    skill_root = tmp_path / "skills" / "media" / "wechat-publisher"
    publish_script = skill_root / "scripts" / "publisher" / "publish.js"
    publish_script.parent.mkdir(parents=True, exist_ok=True)
    publish_script.write_text("// stub", encoding="utf-8")

    result = publish_wechat_draft(
        article_path=str(tmp_path / "missing.md"),
        skill_root=skill_root,
    )

    assert result["ok"] is False
    assert result["error"] == "article_not_found"


def test_publish_wechat_draft_classifies_wechat_ip_whitelist_failure(tmp_path):
    skill_root = tmp_path / "skills" / "media" / "wechat-publisher"
    publish_script = skill_root / "scripts" / "publisher" / "publish.js"
    publish_script.parent.mkdir(parents=True, exist_ok=True)
    publish_script.write_text("// stub", encoding="utf-8")
    article_path = tmp_path / "article.md"
    article_path.write_text("# Draft", encoding="utf-8")

    class _Completed:
        returncode = 1
        stdout = "🔐 正在获取 access_token...\n"
        stderr = "❌ 错误: invalid ip 113.124.103.244 ipv6 ::ffff:113.124.103.244, not in whitelist"

    def fake_run(command, **kwargs):
        return _Completed()

    result = publish_wechat_draft(
        article_path=str(article_path),
        skill_root=skill_root,
        subprocess_run=fake_run,
    )

    assert result["ok"] is False
    assert result["error"] == "wechat_ip_not_whitelisted"
    assert result["failure_summary"] == (
        "微信公众号接口拒绝访问：当前服务器 IP 未加入白名单。文章与配图已生成，请在微信公众平台后台将该服务器 IP 加入白名单后重试。"
    )
    assert result["error_detail"] == (
        "invalid ip 113.124.103.244 ipv6 ::ffff:113.124.103.244, not in whitelist"
    )


def test_publish_wechat_draft_prepares_article_with_uploaded_images_and_normalized_cover(
    tmp_path,
):
    skill_root = tmp_path / "skills" / "media" / "wechat-publisher"
    publish_script = skill_root / "scripts" / "publisher" / "publish.js"
    publish_script.parent.mkdir(parents=True, exist_ok=True)
    publish_script.write_text("// stub", encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (tmp_path / "cover.png").write_bytes(b"cover")
    (tmp_path / "banner.png").write_bytes(b"banner")
    (images_dir / "workflow-map.png").write_bytes(b"workflow")

    article_path = tmp_path / "article.md"
    article_path.write_text(
        "---\n"
        "title: Demo\n"
        "cover: ./cover.jpg\n"
        "---\n\n"
        "![Banner](./banner.jpg)\n\n"
        "![Map](./images/workflow-map.jpg)\n",
        encoding="utf-8",
    )

    uploaded_paths: list[str] = []
    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = "published"
        stderr = ""

    def fake_upload(image_path: Path, access_token: str) -> str:
        uploaded_paths.append(str(image_path))
        return f"https://wx.example/{image_path.name}"

    def fake_access_token_loader(*, skill_root: Path) -> str:
        assert skill_root == skill_root_ref
        return "token-123"

    def fake_run(command, **kwargs):
        prepared_path = Path(command[2])
        captured["command"] = command
        captured["prepared_path"] = prepared_path
        captured["prepared_text"] = prepared_path.read_text(encoding="utf-8")
        captured["kwargs"] = kwargs
        return _Completed()

    skill_root_ref = skill_root
    result = publish_wechat_draft(
        article_path=str(article_path),
        skill_root=skill_root,
        subprocess_run=fake_run,
        wechat_access_token_loader=fake_access_token_loader,
        wechat_image_uploader=fake_upload,
    )

    assert result["ok"] is True
    assert result["article_path"] == str(article_path)
    assert captured["command"] == [
        "node",
        str(publish_script),
        str(captured["prepared_path"]),
        "lapis",
        "solarized-light",
    ]
    assert captured["prepared_path"] != article_path
    assert "cover: ./cover.png" in captured["prepared_text"]
    assert "![Banner](https://wx.example/banner.png)" in captured["prepared_text"]
    assert "![Map](https://wx.example/workflow-map.png)" in captured["prepared_text"]
    assert article_path.read_text(encoding="utf-8").count(".jpg") == 3
    assert uploaded_paths == [
        str(tmp_path / "banner.png"),
        str(images_dir / "workflow-map.png"),
    ]


def test_publish_wechat_draft_creates_wenyan_cache_dir_under_host_home(
    tmp_path,
    monkeypatch,
):
    skill_root = tmp_path / "skills" / "media" / "wechat-publisher"
    publish_script = skill_root / "scripts" / "publisher" / "publish.js"
    publish_script.parent.mkdir(parents=True, exist_ok=True)
    publish_script.write_text("// stub", encoding="utf-8")
    article_path = tmp_path / "article.md"
    article_path.write_text("# Draft", encoding="utf-8")
    host_home = tmp_path / "host-home"
    monkeypatch.setenv("MENTE_HOST_HOME", str(host_home))
    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = "published"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["cache_dir_exists"] = (host_home / ".config" / "wenyan-md").is_dir()
        return _Completed()

    result = publish_wechat_draft(
        article_path=str(article_path),
        skill_root=skill_root,
        subprocess_run=fake_run,
    )

    assert result["ok"] is True
    assert captured["cache_dir_exists"] is True
