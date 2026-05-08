import os
from pathlib import Path

from hermes_constants import (
    bootstrap_mente_home,
    get_mente_home,
    migrate_legacy_hermes_home_to_mente_home,
)
from kernel.codex.home import resolve_private_codex_home
from mente.executors import resolve_runtime_home
from mente.memory.repository import get_default_memory_db_path
from mente.task_core.repository import get_default_task_db_path


def test_resolve_runtime_home_defaults_to_private_mente_path(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_home = resolve_runtime_home()

    assert runtime_home == mente_home / "codex"


def test_resolve_runtime_home_ignores_public_codex_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    public_codex_home = tmp_path / "public-codex-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    runtime_home = resolve_runtime_home()

    assert runtime_home != public_codex_home
    assert runtime_home == mente_home / "codex"


def test_resolve_private_codex_home_ignores_public_codex_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    public_codex_home = tmp_path / "public-codex-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    runtime_home = resolve_private_codex_home()

    assert runtime_home != public_codex_home
    assert runtime_home == mente_home / "codex"


def test_resolve_runtime_home_allows_explicit_mente_override(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    explicit_runtime_home = tmp_path / "mente-runtime-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "public-codex-home"))
    monkeypatch.setenv("MENTE_CODEX_RUNTIME_HOME", str(explicit_runtime_home))

    runtime_home = resolve_runtime_home()

    assert runtime_home == explicit_runtime_home
    assert runtime_home != Path(os.environ["CODEX_HOME"])


def test_get_mente_home_ignores_legacy_hermes_layout(monkeypatch, tmp_path):
    legacy_home = tmp_path / ".hermes" / "mente"
    legacy_home.mkdir(parents=True)
    monkeypatch.delenv("MENTE_HOME", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))

    assert get_mente_home() == tmp_path / ".hermes"


def test_get_hermes_home_prefers_explicit_hermes_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    from hermes_constants import get_hermes_home

    assert get_hermes_home() == hermes_home


def test_mente_default_state_db_paths_follow_mente_home(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("MENTE_TASK_DB_PATH", raising=False)
    monkeypatch.delenv("MENTE_MEMORY_DB_PATH", raising=False)

    assert get_default_task_db_path() == mente_home / "state.db"
    assert get_default_memory_db_path() == mente_home / "state.db"


def test_bootstrap_mente_home_bridges_both_env_vars_to_mente(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    resolved = bootstrap_mente_home()

    assert resolved == mente_home
    assert os.environ["MENTE_HOME"] == str(mente_home)
    assert os.environ["HERMES_HOME"] == str(mente_home)


def test_bootstrap_mente_home_falls_back_to_explicit_hermes_home(monkeypatch, tmp_path):
    hermes_home = tmp_path / "custom-hermes-home"
    monkeypatch.delenv("MENTE_HOME", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    resolved = bootstrap_mente_home()

    assert resolved == hermes_home
    assert os.environ["MENTE_HOME"] == str(hermes_home)
    assert os.environ["HERMES_HOME"] == str(hermes_home)


def test_bootstrap_mente_home_migrates_default_legacy_home(monkeypatch, tmp_path):
    legacy_home = tmp_path / ".hermes"
    legacy_home.mkdir(parents=True)
    (legacy_home / "config.yaml").write_text("model:\n  default: migrated\n", encoding="utf-8")
    (legacy_home / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    (legacy_home / "state.db").write_text("db", encoding="utf-8")
    (legacy_home / "sessions").mkdir()
    (legacy_home / "sessions" / "session.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("MENTE_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    resolved = bootstrap_mente_home()

    mente_home = tmp_path / ".mente"
    assert resolved == mente_home
    assert (mente_home / "config.yaml").read_text(encoding="utf-8").startswith("model:")
    assert (mente_home / ".env").read_text(encoding="utf-8").startswith("OPENAI_API_KEY=")
    assert (mente_home / "state.db").read_text(encoding="utf-8") == "db"
    assert (mente_home / "sessions" / "session.json").read_text(encoding="utf-8") == "{}"
    assert (mente_home / ".migrated-from-hermes").read_text(encoding="utf-8") == str(legacy_home)
    assert os.environ["HERMES_HOME"] == str(mente_home)


def test_migrate_legacy_hermes_home_to_mente_home_is_non_destructive(tmp_path):
    legacy_home = tmp_path / ".hermes"
    mente_home = tmp_path / ".mente"
    legacy_home.mkdir(parents=True)
    mente_home.mkdir(parents=True)
    (legacy_home / "config.yaml").write_text("legacy\n", encoding="utf-8")
    (mente_home / "config.yaml").write_text("new\n", encoding="utf-8")

    migrated = migrate_legacy_hermes_home_to_mente_home(legacy_home, mente_home)

    assert migrated is False
    assert (mente_home / "config.yaml").read_text(encoding="utf-8") == "new\n"
