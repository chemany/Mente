import os
from pathlib import Path

from mente.executors import resolve_runtime_home


def test_resolve_runtime_home_defaults_to_private_mente_path(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    runtime_home = resolve_runtime_home()

    assert runtime_home == hermes_home / "mente" / "codex"


def test_resolve_runtime_home_ignores_public_codex_home(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    public_codex_home = tmp_path / "public-codex-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    runtime_home = resolve_runtime_home()

    assert runtime_home != public_codex_home
    assert runtime_home == hermes_home / "mente" / "codex"


def test_resolve_runtime_home_allows_explicit_mente_override(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    explicit_runtime_home = tmp_path / "mente-runtime-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "public-codex-home"))
    monkeypatch.setenv("MENTE_CODEX_RUNTIME_HOME", str(explicit_runtime_home))

    runtime_home = resolve_runtime_home()

    assert runtime_home == explicit_runtime_home
    assert runtime_home != Path(os.environ["CODEX_HOME"])
