import json

from mente.executors.runtime_config import (
    MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT,
    MENTE_CONTENT_BASE_INSTRUCTIONS,
    MENTE_DEFAULT_BASE_INSTRUCTIONS,
    adapt_runtime_config_for_request,
    resolve_runtime_config,
)
from mente.task_core.models import ExecutionRequest

DEFAULT_BASE_OVERRIDE = f"base_instructions={json.dumps(MENTE_DEFAULT_BASE_INSTRUCTIONS, ensure_ascii=True)}"
DEFAULT_AUTO_COMPACT_OVERRIDE = (
    f"model_auto_compact_token_limit={MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT}"
)


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
    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="gpt-5.4"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
        'model_provider="mente"',
        'model_providers.mente.base_url="https://api.10fu.com/v1"',
        'model_providers.mente.env_key="MENTE_CODEX_API_KEY"',
        'model_providers.mente.name="Mente"',
        'model_providers.mente.requires_openai_auth=false',
        'model_providers.mente.wire_api="responses"',
    ]


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

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="codex-model"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
        'model_provider="mente"',
        'model_providers.mente.base_url="https://codex.invalid/v1"',
        'model_providers.mente.env_key="MENTE_CODEX_API_KEY"',
        'model_providers.mente.name="Mente"',
        'model_providers.mente.requires_openai_auth=false',
        'model_providers.mente.wire_api="responses"',
    ]
    assert runtime_config.subprocess_env == {
        "MENTE_CODEX_API_KEY": "sk-codex",
        "OPENAI_BASE_URL": "https://codex.invalid/v1",
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

    assert runtime_config.to_codex_overrides() == [
        DEFAULT_BASE_OVERRIDE,
        'model="codex-model"',
        DEFAULT_AUTO_COMPACT_OVERRIDE,
        'model_provider="mente"',
        'model_providers.mente.base_url="https://global.invalid/v1"',
        'model_providers.mente.env_key="MENTE_CODEX_API_KEY"',
        'model_providers.mente.name="Mente"',
        'model_providers.mente.requires_openai_auth=false',
        'model_providers.mente.wire_api="responses"',
    ]
    assert runtime_config.subprocess_env == {
        "MENTE_CODEX_API_KEY": "sk-global",
        "OPENAI_BASE_URL": "https://global.invalid/v1",
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


def test_default_runtime_base_instructions_stay_small_but_keep_engineering_guards():
    assert len(MENTE_DEFAULT_BASE_INSTRUCTIONS) < 1000
    assert "coding agent" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "Inspect the workspace" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "If relevant skills are provided" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "follow the skill workflow before improvising" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "diagnose the concrete blocker" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "If skills specify scripts or commands" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "run the most direct one first" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "Do not overwrite user changes" in MENTE_DEFAULT_BASE_INSTRUCTIONS
    assert "Keep responses concise" in MENTE_DEFAULT_BASE_INSTRUCTIONS
