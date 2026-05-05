from mente.executors.runtime_config import resolve_runtime_config


def test_runtime_config_merges_system_profile_and_workspace_layers(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    profile_config = mente_home / "config.toml"
    workspace_config = tmp_path / ".mente" / "codex.toml"
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
                "",
                "[runtime]",
                f'home = "{tmp_path / "profile-runtime-home"}"',
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
                "",
                "[runtime]",
                f'home = "{tmp_path / "workspace-runtime-home"}"',
            ]
        ),
        encoding="utf-8",
    )

    runtime_config = resolve_runtime_config(tmp_path)

    assert runtime_config.runtime_home == tmp_path / "workspace-runtime-home"
    assert runtime_config.ignore_user_config is True
    assert runtime_config.ignore_rules is True
    assert runtime_config.to_codex_overrides() == [
        'model="gpt-5.5"',
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
    assert runtime_config.to_codex_overrides() == []


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
    assert runtime_config.to_codex_overrides() == []


def test_runtime_config_keeps_isolation_flags_stable_with_profile_override(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    profile_config = mente_home / "config.toml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    profile_config.write_text(
        "\n".join(
            [
                "[runtime]",
                f'home = "{tmp_path / "private-runtime-home"}"',
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
        'model="gpt-5.4"',
        'model_provider="mente"',
        'model_providers.mente.base_url="https://api.10fu.com/v1"',
        'model_providers.mente.env_key="MENTE_CODEX_API_KEY"',
        'model_providers.mente.name="Mente"',
        'model_providers.mente.requires_openai_auth=false',
        'model_providers.mente.wire_api="responses"',
    ]
    assert runtime_config.subprocess_env == {
        "MENTE_CODEX_API_KEY": "sk-test-mente",
        "OPENAI_BASE_URL": "https://api.10fu.com/v1",
    }
