import argparse

import pytest


def test_save_model_provider_profile_stores_secret_in_env_only():
    from hermes_cli.config import load_config, load_env, save_config
    from hermes_cli.model_provider_profiles import save_model_provider_profile

    save_config({"providers": {}})

    result = save_model_provider_profile(
        name="My Relay",
        base_url="https://relay.example.com/v1",
        default_model="gpt-5.4-mini",
        api_key="sk-relay-secret",
        slug="my-relay",
        key_env="MY_RELAY_API_KEY",
        api_mode="chat_completions",
        models=["gpt-5.4-mini", "deepseek-chat"],
    )

    assert result["slug"] == "my-relay"
    assert load_env()["MY_RELAY_API_KEY"] == "sk-relay-secret"
    provider_cfg = load_config()["providers"]["my-relay"]
    assert provider_cfg == {
        "name": "My Relay",
        "base_url": "https://relay.example.com/v1",
        "key_env": "MY_RELAY_API_KEY",
        "default_model": "gpt-5.4-mini",
        "api_mode": "chat_completions",
        "models": ["gpt-5.4-mini", "deepseek-chat"],
    }
    assert "api_key" not in provider_cfg


def test_save_model_provider_profile_rejects_invalid_base_url():
    from hermes_cli.model_provider_profiles import ModelProviderProfileError, save_model_provider_profile

    with pytest.raises(ModelProviderProfileError, match="base_url"):
        save_model_provider_profile(
            name="Bad Relay",
            base_url="relay.example.com/v1",
            default_model="gpt-5.4-mini",
        )


def test_cmd_model_add_provider_matches_web_provider_storage():
    from hermes_cli.config import load_config, load_env, save_config
    from hermes_cli.main import cmd_model_add_provider

    save_config({"providers": {}})
    args = argparse.Namespace(
        name="My Relay",
        slug="my-relay",
        base_url="https://relay.example.com/v1",
        api_key="sk-relay-secret",
        key_env="MY_RELAY_API_KEY",
        model="gpt-5.4-mini",
        api_mode="chat_completions",
        models=["deepseek-chat"],
        activate=False,
    )

    cmd_model_add_provider(args)

    assert load_env()["MY_RELAY_API_KEY"] == "sk-relay-secret"
    cfg = load_config()
    assert cfg["providers"]["my-relay"] == {
        "name": "My Relay",
        "base_url": "https://relay.example.com/v1",
        "key_env": "MY_RELAY_API_KEY",
        "default_model": "gpt-5.4-mini",
        "api_mode": "chat_completions",
        "models": ["gpt-5.4-mini", "deepseek-chat"],
    }
    assert "api_key" not in cfg["providers"]["my-relay"]
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        assert model_cfg.get("provider") != "my-relay"


def test_cmd_model_add_provider_can_activate_without_storing_model_api_key():
    from hermes_cli.config import load_config, save_config
    from hermes_cli.main import cmd_model_add_provider

    save_config({"model": {"default": "old-model", "provider": "xiaomi"}, "providers": {}})
    args = argparse.Namespace(
        name="My Relay",
        slug="my-relay",
        base_url="https://relay.example.com/v1",
        api_key="sk-relay-secret",
        key_env="MY_RELAY_API_KEY",
        model="gpt-5.4-mini",
        api_mode="chat_completions",
        models=[],
        activate=True,
    )

    cmd_model_add_provider(args)

    model_cfg = load_config()["model"]
    assert model_cfg["provider"] == "my-relay"
    assert model_cfg["default"] == "gpt-5.4-mini"
    assert model_cfg["base_url"] == "https://relay.example.com/v1"
    assert model_cfg["api_mode"] == "chat_completions"
    assert "api_key" not in model_cfg
