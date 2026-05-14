import json
from pathlib import Path

import pytest
import yaml

from mente.context_builder.builder import ContextBuilder
from mente.executors.runtime_config import (
    MENTE_CONVERSATION_BASE_INSTRUCTIONS,
    MENTE_COORDINATOR_BASE_INSTRUCTIONS,
    MENTE_CONFIG_ADMIN_BASE_INSTRUCTIONS,
    MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT,
    MENTE_CONTENT_BASE_INSTRUCTIONS,
    MENTE_DEFAULT_BASE_INSTRUCTIONS,
    MENTE_RESEARCH_BASE_INSTRUCTIONS,
    MENTE_SELF_KNOWLEDGE,
    MENTE_WRITING_BASE_INSTRUCTIONS,
    adapt_runtime_config_for_request,
    resolve_runtime_config,
)
from mente.task_core.models import ExecutionRequest, Task

DEFAULT_BASE_OVERRIDE = f"base_instructions={json.dumps(MENTE_DEFAULT_BASE_INSTRUCTIONS, ensure_ascii=True)}"
DEFAULT_AUTO_COMPACT_OVERRIDE = (
    f"model_auto_compact_token_limit={MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT}"
)
DEFAULT_AGENT_IDS = {
    "coordinator": "executive_office",
    "director": "executive_office",
    "engineering": "product_engineering",
    "research": "strategy_research",
    "writing": "editorial",
    "config_admin": "platform_operations",
    "content_publishing": "publishing_operations",
}


def _write_legacy_lane_soul(mente_home, name: str, text: str) -> None:
    souls_dir = mente_home / "souls"
    souls_dir.mkdir(parents=True, exist_ok=True)
    (souls_dir / f"{name}.md").write_text(text, encoding="utf-8")


def _agent_dir(mente_home: Path, agent_id: str) -> Path:
    return mente_home / "agents" / agent_id


def _agent_runtime_home(mente_home: Path, agent_id: str) -> Path:
    return mente_home / "runtime" / "agents" / agent_id / "codex"


def _write_agent_soul(mente_home: Path, agent_id: str, text: str) -> None:
    agent_dir = _agent_dir(mente_home, agent_id)
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "soul.md").write_text(text, encoding="utf-8")


def _load_agent_registry(mente_home: Path) -> dict[str, object]:
    return yaml.safe_load((mente_home / "agents" / "registry.yaml").read_text(encoding="utf-8")) or {}


def test_runtime_config_merges_profile_and_workspace_yaml_layers(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    workspace = tmp_path / "workspace"
    profile_config = mente_home / "config.yaml"
    workspace_config = workspace / ".mente" / "config.yaml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    workspace_config.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    profile_config.write_text(
        "\n".join(
            [
                "codex:",
                '  model_provider: "profile"',
                '  model: "gpt-5.4"',
                "  model_providers:",
                "    profile:",
                '      name: "vipnewapi"',
                '      base_url: "https://profile.invalid/v1"',
                "  runtime:",
                f'    home: "{tmp_path / "profile-runtime-home"}"',
            ]
        ),
        encoding="utf-8",
    )
    workspace_config.write_text(
        "\n".join(
            [
                "codex:",
                '  model: "gpt-5.5"',
                "  model_providers:",
                "    profile:",
                '      wire_api: "responses"',
                "  runtime:",
                f'    home: "{workspace / "workspace-runtime-home"}"',
            ]
        ),
        encoding="utf-8",
    )

    runtime_config = resolve_runtime_config(workspace)

    assert runtime_config.runtime_home == workspace / "workspace-runtime-home"
    assert runtime_config.ignore_user_config is True
    assert runtime_config.ignore_rules is True
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="gpt-5.5"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
        'model_provider="profile"',
        'model_providers.profile.base_url="https://profile.invalid/v1"',
        'model_providers.profile.name="vipnewapi"',
        'model_providers.profile.wire_api="responses"',
    ]


def test_runtime_config_ignores_public_codex_user_config_by_default(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "config.toml").write_text(
        "\n".join(
            [
                'model_provider = "public"',
                'model = "gpt-5-public"',
                "",
                "[model_providers.public]",
                'base_url = "https://public.invalid/v1"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.runtime_home == mente_home / "codex"
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]


def test_runtime_config_prefers_yaml_over_legacy_toml_when_both_exist(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    workspace = tmp_path / "workspace"
    profile_yaml = mente_home / "config.yaml"
    profile_toml = mente_home / "config.toml"
    workspace_yaml = workspace / ".mente" / "config.yaml"
    workspace_toml = workspace / ".mente" / "codex.toml"
    profile_yaml.parent.mkdir(parents=True, exist_ok=True)
    workspace_yaml.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    profile_toml.write_text(
        "\n".join(
            [
                'model_provider = "legacy"',
                'model = "legacy-profile"',
            ]
        ),
        encoding="utf-8",
    )
    workspace_toml.write_text(
        "\n".join(
            [
                'model = "legacy-workspace"',
            ]
        ),
        encoding="utf-8",
    )
    profile_yaml.write_text(
        "\n".join(
            [
                "codex:",
                '  model_provider: "yaml"',
                '  model: "yaml-profile"',
            ]
        ),
        encoding="utf-8",
    )
    workspace_yaml.write_text(
        "\n".join(
            [
                "codex:",
                '  model: "yaml-workspace"',
            ]
        ),
        encoding="utf-8",
    )

    runtime_config = resolve_runtime_config(workspace)

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="yaml-workspace"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
        'model_provider="yaml"',
    ]


def test_runtime_config_uses_legacy_toml_fallback_when_yaml_absent(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    workspace = tmp_path / "workspace"
    profile_config = mente_home / "config.toml"
    workspace_config = workspace / ".mente" / "codex.toml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    workspace_config.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    profile_config.write_text(
        "\n".join(
            [
                'model_provider = "profile"',
                'model = "gpt-5.4"',
                "",
                "[model_providers.profile]",
                'name = "vipnewapi"',
                'base_url = "https://profile.invalid/v1"',
            ]
        ),
        encoding="utf-8",
    )
    workspace_config.write_text(
        "\n".join(
            [
                'model = "gpt-5.5"',
                "",
                "[model_providers.profile]",
                'wire_api = "responses"',
            ]
        ),
        encoding="utf-8",
    )

    runtime_config = resolve_runtime_config(workspace)

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="gpt-5.5"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
        'model_provider="profile"',
        'model_providers.profile.base_url="https://profile.invalid/v1"',
        'model_providers.profile.name="vipnewapi"',
        'model_providers.profile.wire_api="responses"',
    ]


def test_runtime_config_ignores_legacy_hermes_mente_config(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    legacy_home = tmp_path / ".hermes" / "mente"
    legacy_home.mkdir(parents=True, exist_ok=True)
    (legacy_home / "config.toml").write_text(
        'model = "legacy"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.runtime_home == mente_home / "codex"
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]


def test_runtime_config_keeps_isolation_flags_stable_with_profile_override(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    profile_config = mente_home / "config.yaml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    profile_config.write_text(
        "\n".join(
            [
                "codex:",
                "  runtime:",
                f'    home: "{tmp_path / "private-runtime-home"}"',
            ]
        ),
        encoding="utf-8",
    )

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.runtime_home == tmp_path / "private-runtime-home"
    assert runtime_config.ignore_user_config is True
    assert runtime_config.ignore_rules is True


def test_runtime_config_falls_back_to_mente_model_settings_for_private_provider(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                '  default: "gpt-5.4"',
                '  base_url: "https://api.10fu.com/v1"',
                '  api_key: "sk-test-mente"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.runtime_home == mente_home / "codex"
    assert runtime_config.model_runtime.model == "gpt-5.4"
    assert runtime_config.model_runtime.base_url == "https://api.10fu.com/v1"
    assert runtime_config.model_runtime.api_mode == "chat_completions"
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="gpt-5.4"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]
    assert runtime_config.subprocess_env == {
        "MENTE_CODEX_API_KEY": "sk-test-mente",
    }


def test_runtime_config_detects_anthropic_mode_from_mente_model_settings_without_codex_provider_override(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                '  default: "mimo-v2.5-pro"',
                '  provider: "xiaomi"',
                '  base_url: "https://token-plan-cn.xiaomimimo.com/anthropic"',
                '  api_key: "sk-test-mente"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.runtime_home == mente_home / "codex"
    assert runtime_config.model_runtime.provider == "xiaomi"
    assert runtime_config.model_runtime.model == "mimo-v2.5-pro"
    assert runtime_config.model_runtime.base_url == "https://token-plan-cn.xiaomimimo.com/anthropic"
    assert runtime_config.model_runtime.api_mode == "anthropic_messages"
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="mimo-v2.5-pro"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]


def test_runtime_config_resolves_provider_api_key_from_mente_env_without_model_secret(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                '  default: "mimo-v2.5-pro"',
                '  provider: "xiaomi"',
                '  base_url: "https://token-plan-cn.xiaomimimo.com/anthropic"',
                '  api_mode: "anthropic_messages"',
            ]
        ),
        encoding="utf-8",
    )
    (mente_home / ".env").write_text("XIAOMI_API_KEY=sk-test-xiaomi\n", encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.model_runtime.provider == "xiaomi"
    assert runtime_config.model_runtime.api_mode == "anthropic_messages"
    assert runtime_config.subprocess_env["MENTE_CODEX_API_KEY"] == "sk-test-xiaomi"


def test_adapt_runtime_config_for_content_publishing_switches_to_content_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher", "imagegen"],
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_CONTENT_BASE_INSTRUCTIONS
    assert adapted.codex_config["agents"]["job_max_runtime_seconds"] == 300


def test_adapt_runtime_config_for_config_admin_switches_to_config_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Update Mente configuration.",
        user_request="把 terminal.cwd 改成 / 并重启 gateway",
        workspace=str(tmp_path),
        skill_refs=["software-development/mente-config-admin"],
        metadata={"source": "gateway", "task_profile": "config_admin"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_CONFIG_ADMIN_BASE_INSTRUCTIONS
    assert "agents" not in adapted.codex_config or "job_max_runtime_seconds" not in adapted.codex_config["agents"]


def test_adapt_runtime_config_for_plain_conversation_switches_to_thin_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是什么大模型",
        workspace=str(tmp_path),
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_CONVERSATION_BASE_INSTRUCTIONS


def test_adapt_runtime_config_for_coordinator_role_uses_thin_base_instructions(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Acknowledge and delegate",
        user_request="先帮我分派这个任务",
        workspace=str(tmp_path),
        role="coordinator",
        dispatch_mode="inline",
        worker_lane="research",
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_COORDINATOR_BASE_INSTRUCTIONS


def test_adapt_runtime_config_for_coordinator_real_chain_keeps_thin_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    task = Task(
        task_id="task_real_chain",
        session_id="session_1",
        task_type="conversation",
        objective="Acknowledge and delegate",
        user_request="先帮我派给 research 去做",
        workspace=str(tmp_path),
        parent_task_id="task_parent",
        job_id="job_123",
        role="coordinator",
        dispatch_mode="delegate_background",
        worker_lane="research",
        worker_skill_refs=["research/deep-dive"],
        metadata={"source": "gateway"},
    )

    request = ContextBuilder().build(task)
    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert request.parent_task_id == "task_parent"
    assert request.job_id == "job_123"
    assert request.role.value == "coordinator"
    assert request.dispatch_mode.value == "delegate_background"
    assert request.worker_lane == "research"
    assert request.worker_skill_refs == ["research/deep-dive"]
    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_COORDINATOR_BASE_INSTRUCTIONS


def test_adapt_runtime_config_for_director_lane_uses_coordinator_thin_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="继续",
        workspace=str(tmp_path),
        metadata={"lane": "director"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_COORDINATOR_BASE_INSTRUCTIONS


@pytest.mark.parametrize(
    ("worker_lane", "expected_base_instructions"),
    [
        ("research", MENTE_RESEARCH_BASE_INSTRUCTIONS),
        ("writing", MENTE_WRITING_BASE_INSTRUCTIONS),
        ("config_admin", MENTE_CONFIG_ADMIN_BASE_INSTRUCTIONS),
        ("engineering", MENTE_DEFAULT_BASE_INSTRUCTIONS),
    ],
)
def test_adapt_runtime_config_for_coordinator_worker_lanes_keeps_existing_prompts(
    tmp_path,
    worker_lane: str,
    expected_base_instructions: str,
):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id=f"task_{worker_lane}",
        session_id="session_1",
        task_type="conversation",
        objective=f"Worker lane {worker_lane}",
        user_request=f"worker request for {worker_lane}",
        workspace=str(tmp_path),
        role="worker",
        dispatch_mode="delegate_background",
        worker_lane=worker_lane,
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == expected_base_instructions


def test_adapt_runtime_config_for_research_lane_switches_to_research_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Research the market positioning of open-source coding agents",
        user_request="调研一下开源 coding agent 的市场定位和差异",
        workspace=str(tmp_path),
        metadata={"lane": "research"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_RESEARCH_BASE_INSTRUCTIONS


def test_adapt_runtime_config_for_writing_lane_switches_to_writing_profile(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft a concise launch announcement",
        user_request="帮我写一版产品发布短文案，语气克制一点",
        workspace=str(tmp_path),
        metadata={"lane": "writing"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_WRITING_BASE_INSTRUCTIONS


def test_adapt_runtime_config_for_coordinator_preserves_deep_research_runtime_selection(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_deep_research",
        session_id="session_1",
        task_type="conversation",
        objective="Research deeply",
        user_request="做一份深度研究",
        workspace=str(tmp_path),
        role="worker",
        dispatch_mode="delegate_background",
        metadata={"task_profile": "deep_research"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted is not runtime_config
    assert adapted.codex_config["base_instructions"] == MENTE_RESEARCH_BASE_INSTRUCTIONS


def test_adapt_runtime_config_keeps_default_engineering_base_for_project_requests(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Implement a feature in this repository",
        user_request="请帮我在这个项目里新增登录功能并完成测试",
        workspace=str(tmp_path),
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted.codex_config["base_instructions"] == MENTE_DEFAULT_BASE_INSTRUCTIONS


def test_runtime_config_profile_overrides_apply_from_codex_yaml(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  profiles:",
                "    content_publishing:",
                '      base_instructions: "custom publishing instructions"',
                "      agents:",
                "        job_max_runtime_seconds: 420",
                "    config_admin:",
                '      base_instructions: "custom config instructions"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    publishing_request = ExecutionRequest(
        task_id="task_publish",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher"],
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )
    config_admin_request = ExecutionRequest(
        task_id="task_config",
        session_id="session_1",
        task_type="conversation",
        objective="Update Mente configuration.",
        user_request="把 terminal.cwd 改成 / 并重启 gateway",
        workspace=str(tmp_path),
        skill_refs=["software-development/mente-config-admin"],
        metadata={"source": "gateway", "task_profile": "config_admin"},
    )

    adapted_publishing = adapt_runtime_config_for_request(runtime_config, publishing_request)
    adapted_config_admin = adapt_runtime_config_for_request(runtime_config, config_admin_request)

    assert adapted_publishing.codex_config["base_instructions"] == "custom publishing instructions"
    assert adapted_publishing.codex_config["agents"]["job_max_runtime_seconds"] == 420
    assert adapted_config_admin.codex_config["base_instructions"] == "custom config instructions"


def test_runtime_config_profile_overrides_apply_for_lane_profiles(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  profiles:",
                "    research:",
                '      base_instructions: "custom research instructions"',
                "    writing:",
                '      base_instructions: "custom writing instructions"',
                "    director:",
                '      base_instructions: "custom director instructions"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    research_request = ExecutionRequest(
        task_id="task_research",
        session_id="session_1",
        task_type="conversation",
        objective="Research the market positioning of open-source coding agents",
        user_request="调研一下开源 coding agent 的市场定位和差异",
        workspace=str(tmp_path),
        metadata={"lane": "research"},
    )
    writing_request = ExecutionRequest(
        task_id="task_writing",
        session_id="session_1",
        task_type="conversation",
        objective="Draft a concise launch announcement",
        user_request="帮我写一版产品发布短文案，语气克制一点",
        workspace=str(tmp_path),
        metadata={"lane": "writing"},
    )
    director_request = ExecutionRequest(
        task_id="task_director",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是谁",
        workspace=str(tmp_path),
        metadata={"lane": "director"},
    )

    adapted_research = adapt_runtime_config_for_request(runtime_config, research_request)
    adapted_writing = adapt_runtime_config_for_request(runtime_config, writing_request)
    adapted_director = adapt_runtime_config_for_request(runtime_config, director_request)

    assert adapted_research.codex_config["base_instructions"] == "custom research instructions"
    assert adapted_writing.codex_config["base_instructions"] == "custom writing instructions"
    assert adapted_director.codex_config["base_instructions"] == "custom director instructions"


def test_runtime_config_seeds_agent_registry_structure_under_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    registry = _load_agent_registry(mente_home)
    executive_office_dir = _agent_dir(mente_home, "executive_office")
    executive_office_runtime = _agent_runtime_home(mente_home, "executive_office")

    assert runtime_config.codex_config["base_instructions"] == MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert registry["version"] == 1
    assert registry["lanes"]["coordinator"] == "executive_office"
    assert registry["lanes"]["director"] == "executive_office"
    assert registry["task_profiles"]["content_publishing"] == "publishing_operations"
    assert executive_office_dir.is_dir()
    assert (executive_office_dir / "agent.yaml").is_file()
    assert (executive_office_dir / "soul.md").is_file()
    assert executive_office_runtime.is_dir()


def test_runtime_config_upgrades_known_legacy_builtin_agent_soul(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    agent_dir = _agent_dir(mente_home, DEFAULT_AGENT_IDS["engineering"])
    agent_dir.mkdir(parents=True, exist_ok=True)
    old_builtin_soul = (
        "You are Mente's coding agent. Inspect only the minimum relevant workspace context before changing code. "
        "For deterministic tasks with an explicit file, command, config key, or skill workflow, go directly to that target instead of broad exploration. "
        "For code-logic, default-value provenance, compatibility-sensitive, or multi-file behavior changes, inspect the relevant implementation and affected files before editing. "
        "If relevant skills are provided, read them first and follow the skill workflow before improvising. "
        "If skills specify scripts or commands, run the most direct one first. "
        "If that workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. "
        "Keep edits minimal, correct, and consistent with the existing codebase. "
        "Do not overwrite user changes you did not make or use destructive git/file operations unless explicitly requested. "
        "Keep responses concise, action-oriented, and focused on the task result."
    )
    (agent_dir / "soul.md").write_text(old_builtin_soul, encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    resolve_runtime_config(tmp_path)

    upgraded = (agent_dir / "soul.md").read_text(encoding="utf-8")
    assert MENTE_SELF_KNOWLEDGE in upgraded


def test_runtime_config_upgrades_previous_self_knowledge_agent_soul(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    agent_dir = _agent_dir(mente_home, DEFAULT_AGENT_IDS["engineering"])
    agent_dir.mkdir(parents=True, exist_ok=True)
    previous_self_knowledge_soul = (
        "You are Mente's coding agent. "
        "Mente is a self-hosted multi-agent assistant. "
        "The coordinator owns user turns, clarification, delegation, status, and worker control; "
        "background workers execute lane work such as engineering, research, writing, config_admin, and publishing. "
        "Worker jobs record task/job metadata, progress, terminal checkpoints, and controls in persisted state. "
        "Explicit skills route through skill ownership; unknown or cross-lane skill requests should clarify instead of guessing. "
        "Model switching uses config.yaml provider profiles plus .env secrets, shared by dashboard and CLI. "
        "Memory uses the unified Mente memory store with optional LLM memory review; do not create private per-runtime memories unless explicitly scoped. "
        "Inspect only the minimum relevant workspace context before changing code."
    )
    (agent_dir / "soul.md").write_text(previous_self_knowledge_soul, encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    resolve_runtime_config(tmp_path)

    upgraded = (agent_dir / "soul.md").read_text(encoding="utf-8")
    assert "It is safe to tell users that API keys are stored" in upgraded


def test_runtime_config_does_not_overwrite_custom_agent_soul(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    agent_dir = _agent_dir(mente_home, DEFAULT_AGENT_IDS["engineering"])
    agent_dir.mkdir(parents=True, exist_ok=True)
    custom_soul = "Custom engineering soul that intentionally owns its own context."
    (agent_dir / "soul.md").write_text(custom_soul, encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    resolve_runtime_config(tmp_path)

    assert (agent_dir / "soul.md").read_text(encoding="utf-8") == custom_soul


def test_runtime_config_coordinator_registry_keeps_director_compatibility(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    resolve_runtime_config(tmp_path)
    registry = _load_agent_registry(mente_home)

    assert registry["lanes"]["coordinator"] == DEFAULT_AGENT_IDS["coordinator"]
    assert registry["lanes"]["director"] == DEFAULT_AGENT_IDS["director"]


def test_runtime_config_uses_agent_soul_override_from_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    _write_agent_soul(
        mente_home,
        DEFAULT_AGENT_IDS["director"],
        "You are the executive office soul from file.",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_director",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是谁",
        workspace=str(tmp_path),
        metadata={"lane": "director"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted.codex_config["base_instructions"] == "You are the executive office soul from file."


def test_runtime_config_reloads_agent_soul_on_each_request(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    _write_agent_soul(mente_home, DEFAULT_AGENT_IDS["research"], "Research strategy soul v1")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_research",
        session_id="session_1",
        task_type="conversation",
        objective="Research the market positioning of open-source coding agents",
        user_request="调研一下开源 coding agent 的市场定位和差异",
        workspace=str(tmp_path),
        metadata={"lane": "research"},
    )

    adapted_v1 = adapt_runtime_config_for_request(runtime_config, request)
    _write_agent_soul(mente_home, DEFAULT_AGENT_IDS["research"], "Research strategy soul v2")
    adapted_v2 = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted_v1.codex_config["base_instructions"] == "Research strategy soul v1"
    assert adapted_v2.codex_config["base_instructions"] == "Research strategy soul v2"


def test_runtime_config_content_publishing_agent_soul_override_beats_profile_base_instruction(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  profiles:",
                "    content_publishing:",
                '      base_instructions: "config profile publishing instructions"',
            ]
        ),
        encoding="utf-8",
    )
    _write_agent_soul(
        mente_home,
        DEFAULT_AGENT_IDS["content_publishing"],
        "Publishing operations soul from file.",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_publish",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher"],
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted.codex_config["base_instructions"] == "Publishing operations soul from file."


def test_runtime_config_routes_default_runtime_home_to_agent_scoped_codex_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    director_request = ExecutionRequest(
        task_id="task_director",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是谁",
        workspace=str(tmp_path),
        metadata={"lane": "director"},
    )
    engineering_request = ExecutionRequest(
        task_id="task_engineering",
        session_id="session_1",
        task_type="engineering",
        objective="Implement feature",
        user_request="实现一个功能",
        workspace=str(tmp_path),
    )
    publishing_request = ExecutionRequest(
        task_id="task_publish",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher"],
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    adapted_director = adapt_runtime_config_for_request(runtime_config, director_request)
    adapted_engineering = adapt_runtime_config_for_request(runtime_config, engineering_request)
    adapted_publishing = adapt_runtime_config_for_request(runtime_config, publishing_request)

    assert adapted_director.runtime_home == _agent_runtime_home(
        mente_home, DEFAULT_AGENT_IDS["director"]
    )
    assert adapted_engineering.runtime_home == _agent_runtime_home(
        mente_home, DEFAULT_AGENT_IDS["engineering"]
    )
    assert adapted_publishing.runtime_home == _agent_runtime_home(
        mente_home, DEFAULT_AGENT_IDS["content_publishing"]
    )
    assert adapted_director.runtime_home.is_dir()
    assert adapted_engineering.runtime_home.is_dir()
    assert adapted_publishing.runtime_home.is_dir()


def test_runtime_config_preserves_explicit_runtime_home_without_agent_sharding(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    explicit_runtime_home = tmp_path / "custom-runtime-home"
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  runtime:",
                f'    home: "{explicit_runtime_home}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    request = ExecutionRequest(
        task_id="task_director",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是谁",
        workspace=str(tmp_path),
        metadata={"lane": "director"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert runtime_config.runtime_home == explicit_runtime_home
    assert adapted.runtime_home == explicit_runtime_home


def test_runtime_config_migrates_legacy_souls_into_agent_storage_and_deletes_legacy_files(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    _write_legacy_lane_soul(mente_home, "director", "You are the legacy director soul from file.")
    _write_legacy_lane_soul(mente_home, "content_publishing", "Legacy publishing soul from file.")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)
    director_request = ExecutionRequest(
        task_id="task_director",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是谁",
        workspace=str(tmp_path),
        metadata={"lane": "director"},
    )
    publishing_request = ExecutionRequest(
        task_id="task_publish",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher"],
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    adapted_director = adapt_runtime_config_for_request(runtime_config, director_request)
    adapted_publishing = adapt_runtime_config_for_request(runtime_config, publishing_request)

    assert adapted_director.codex_config["base_instructions"] == "You are the legacy director soul from file."
    assert adapted_publishing.codex_config["base_instructions"] == "Legacy publishing soul from file."
    assert (
        _agent_dir(mente_home, DEFAULT_AGENT_IDS["director"]) / "soul.md"
    ).read_text(encoding="utf-8") == "You are the legacy director soul from file."
    assert (
        _agent_dir(mente_home, DEFAULT_AGENT_IDS["content_publishing"]) / "soul.md"
    ).read_text(encoding="utf-8") == "Legacy publishing soul from file."
    assert not (mente_home / "souls" / "director.md").exists()
    assert not (mente_home / "souls" / "content_publishing.md").exists()
    assert not (mente_home / "souls").exists()


def test_runtime_config_profile_overrides_are_not_forwarded_as_raw_codex_overrides(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  profiles:",
                "    content_publishing:",
                "      agents:",
                "        job_max_runtime_seconds: 420",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]


def test_adapt_runtime_config_preserves_explicit_base_instructions(tmp_path):
    runtime_config = resolve_runtime_config(tmp_path)
    runtime_config.codex_config["base_instructions"] = "Custom operator instructions."
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher"],
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    adapted = adapt_runtime_config_for_request(runtime_config, request)

    assert adapted.codex_config["base_instructions"] == "Custom operator instructions."
    assert adapted.codex_config["agents"]["job_max_runtime_seconds"] == 300
    assert adapted.subprocess_env == runtime_config.subprocess_env


def test_runtime_config_dedicated_codex_settings_override_global_model_defaults(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                '  default: "global-model"',
                '  base_url: "https://global.invalid/v1"',
                '  api_key: "sk-global"',
                "codex:",
                '  default: "codex-model"',
                '  base_url: "https://codex.invalid/v1"',
                '  api_key: "sk-codex"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.model_runtime.model == "codex-model"
    assert runtime_config.model_runtime.base_url == "https://codex.invalid/v1"
    assert runtime_config.model_runtime.api_mode == "chat_completions"
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="codex-model"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]
    assert runtime_config.subprocess_env == {
        "MENTE_CODEX_API_KEY": "sk-codex",
    }


def test_runtime_config_codex_model_only_inherits_global_provider_settings(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                '  default: "global-model"',
                '  base_url: "https://global.invalid/v1"',
                '  api_key: "sk-global"',
                "codex:",
                '  default: "codex-model"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.model_runtime.model == "codex-model"
    assert runtime_config.model_runtime.base_url == "https://global.invalid/v1"
    assert runtime_config.model_runtime.api_mode == "chat_completions"
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="codex-model"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]
    assert runtime_config.subprocess_env == {
        "MENTE_CODEX_API_KEY": "sk-global",
    }


def test_runtime_config_injects_default_slim_base_instructions_when_unset(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]


def test_runtime_config_prefers_explicit_base_instructions_over_mente_default(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                '  base_instructions: "project-specific-runtime-guardrails"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.to_codex_overrides() == [
        'base_instructions="project-specific-runtime-guardrails"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
    ]


def test_runtime_config_preserves_explicit_auto_compact_limit(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  model_auto_compact_token_limit: 120000",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        "model_auto_compact_token_limit=120000",
    ]


def test_runtime_config_resolves_launcher_flags_from_codex_runtime_yaml(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                "  runtime:",
                '    sandbox: "danger-full-access"',
                '    approval_policy: "on-request"',
                "    skip_git_repo_check: false",
                '    color: "always"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.sandbox == "danger-full-access"
    assert runtime_config.approval_policy == "on-request"
    assert runtime_config.skip_git_repo_check is False
    assert runtime_config.color == "always"


def test_default_runtime_base_instructions_stay_small_but_keep_engineering_guards():
    assert len(MENTE_DEFAULT_BASE_INSTRUCTIONS) < 1700
    assert "coding agent" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "minimum relevant workspace context" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "explicit file, command, config key, or skill workflow" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "default-value provenance" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "compatibility-sensitive" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "If relevant skills are provided" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "follow the skill workflow before improvising" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "diagnose the concrete blocker" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "If skills specify scripts or commands" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "run the most direct one first" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "Do not overwrite user changes" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "Keep responses concise" in MENTE_DEFAULT_BASE_INSTRUCTIONS


def test_runtime_base_instructions_include_current_mente_self_knowledge():
    assert len(MENTE_SELF_KNOWLEDGE) < 1100
    for phrase in [
        "coordinator",
        "background workers",
        "skill ownership",
        "provider profiles",
        "API keys are stored",
        "not secret values",
        "LLM memory review",
    ]:
        assert phrase in MENTE_SELF_KNOWLEDGE

    for instructions in [
        MENTE_COORDINATOR_BASE_INSTRUCTIONS,
        MENTE_DEFAULT_BASE_INSTRUCTIONS,
        MENTE_CONFIG_ADMIN_BASE_INSTRUCTIONS,
        MENTE_CONTENT_BASE_INSTRUCTIONS,
    ]:
        assert MENTE_SELF_KNOWLEDGE in instructions
