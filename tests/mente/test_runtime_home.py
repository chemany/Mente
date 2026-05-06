import os
from pathlib import Path

from hermes_constants import get_mente_home
from kernel.codex.home import resolve_private_codex_home
from mente.executors import resolve_runtime_home


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
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert get_mente_home() == tmp_path / ".mente"


def test_get_hermes_home_prefers_explicit_hermes_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    from hermes_constants import get_hermes_home

    assert get_hermes_home() == hermes_home
