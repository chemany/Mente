import yaml

from kernel.codex.config import migrate_legacy_private_codex_config


def test_migrate_legacy_private_codex_config_writes_profile_yaml_codex_section(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.toml").write_text(
        "\n".join(
            [
                'model = "gpt-5.4"',
                'model_provider = "profile"',
                "",
                "[model_providers.profile]",
                'base_url = "https://profile.invalid/v1"',
            ]
        ),
        encoding="utf-8",
    )
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                '  default: "global-model"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    result = migrate_legacy_private_codex_config()

    payload = yaml.safe_load((mente_home / "config.yaml").read_text(encoding="utf-8"))
    assert result["profile"] == "migrated"
    assert payload["model"]["default"] == "global-model"
    assert payload["codex"] == {
        "model": "gpt-5.4",
        "model_provider": "profile",
        "model_providers": {
            "profile": {
                "base_url": "https://profile.invalid/v1",
            }
        },
    }


def test_migrate_legacy_private_codex_config_writes_workspace_yaml_codex_section(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    workspace = tmp_path / "workspace"
    workspace_mente = workspace / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    workspace_mente.mkdir(parents=True, exist_ok=True)
    (workspace_mente / "codex.toml").write_text(
        "\n".join(
            [
                'model = "workspace-model"',
                "",
                "[runtime]",
                f'home = "{workspace / "private-runtime-home"}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    result = migrate_legacy_private_codex_config(workspace=workspace)

    payload = yaml.safe_load((workspace_mente / "config.yaml").read_text(encoding="utf-8"))
    assert result["workspace"] == "migrated"
    assert payload["codex"] == {
        "model": "workspace-model",
        "runtime": {
            "home": str(workspace / "private-runtime-home"),
        },
    }


def test_migrate_legacy_private_codex_config_does_not_override_existing_codex_yaml(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "config.toml").write_text('model = "legacy-model"\n', encoding="utf-8")
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "codex:",
                '  model: "yaml-model"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    result = migrate_legacy_private_codex_config()

    payload = yaml.safe_load((mente_home / "config.yaml").read_text(encoding="utf-8"))
    assert result["profile"] == "skipped_existing_yaml_codex"
    assert payload["codex"] == {"model": "yaml-model"}
