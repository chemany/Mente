from mente.feature_flags import build_conversation_workflow_contract


def test_llm_memory_review_defaults_enabled_without_config_or_env(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(mente_home))
    monkeypatch.delenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("MENTE_LLM_MEMORY_REVIEW_SOURCES", raising=False)

    contract = build_conversation_workflow_contract(source="gateway")

    assert contract["llm_memory_review"]["enabled"] is True


def test_llm_memory_review_reads_config_yaml_without_restart(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir()
    config_path = mente_home / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(mente_home))
    monkeypatch.delenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("MENTE_LLM_MEMORY_REVIEW_SOURCES", raising=False)

    config_path.write_text(
        "memory:\n"
        "  llm_review:\n"
        "    enabled: true\n"
        "    sources: [gateway, tui]\n",
        encoding="utf-8",
    )

    enabled_contract = build_conversation_workflow_contract(source="gateway")
    api_contract = build_conversation_workflow_contract(source="api_server")

    assert enabled_contract["llm_memory_review"]["enabled"] is True
    assert api_contract["llm_memory_review"]["enabled"] is False

    config_path.write_text(
        "memory:\n"
        "  llm_review:\n"
        "    enabled: false\n"
        "    sources: [gateway, tui]\n",
        encoding="utf-8",
    )

    disabled_contract = build_conversation_workflow_contract(source="gateway")

    assert disabled_contract["llm_memory_review"]["enabled"] is False


def test_llm_memory_review_env_override_wins_over_config_yaml(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir()
    (mente_home / "config.yaml").write_text(
        "memory:\n"
        "  llm_review:\n"
        "    enabled: true\n"
        "    sources: [gateway]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "0")
    monkeypatch.delenv("MENTE_LLM_MEMORY_REVIEW_SOURCES", raising=False)

    contract = build_conversation_workflow_contract(source="gateway")

    assert contract["llm_memory_review"]["enabled"] is False
