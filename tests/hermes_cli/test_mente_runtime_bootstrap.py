from pathlib import Path
import os
import sys

from hermes_cli.config import (
    default_release_install_policy,
    get_release_install_manifest_path,
    load_release_install_manifest,
    save_release_install_manifest,
)
from hermes_cli.runtime_override import apply_source_checkout_runtime_override


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_install_policy_defaults_to_release_pinned_contract():
    policy = default_release_install_policy()

    assert policy["install_mode"] == "release"
    assert policy["update_policy"] == "git_tag_release"
    assert policy["runtime_bootstrap_policy"] == "artifact_manifest_and_runtime_wheel"
    assert policy["developer_setup_path"] == "./setup-hermes.sh"
    assert policy["one_click_install_policy"] == "release_pinned"


def test_release_install_manifest_round_trip(tmp_path):
    payload = {
        "install_mode": "release",
        "release_ref": "v2026.4.30",
        "runtime_artifact_manifest": "/tmp/manifest.json",
        "runtime_wheel": "/tmp/runtime.whl",
    }

    path = save_release_install_manifest(payload, tmp_path)
    loaded = load_release_install_manifest(tmp_path)

    assert path == get_release_install_manifest_path(tmp_path)
    assert loaded is not None
    assert loaded["release_ref"] == "v2026.4.30"
    assert loaded["runtime_artifact_manifest"] == "/tmp/manifest.json"
    assert loaded["runtime_wheel"] == "/tmp/runtime.whl"
    assert loaded["developer_setup_path"] == "./setup-hermes.sh"


def test_install_scripts_advertise_release_pinned_and_offline_runtime_bootstrap():
    install_sh = (REPO_ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    install_ps1 = (REPO_ROOT / "scripts/install.ps1").read_text(encoding="utf-8")

    for content in (install_sh, install_ps1):
        lowered = content.lower()
        assert "release" in lowered
        assert "runtime" in lowered
        assert "artifact" in lowered

    assert "--release" in install_sh
    assert "--runtime-wheel" in install_sh
    assert "RuntimeWheel" in install_ps1


def test_setup_hermes_is_marked_as_developer_source_checkout_path():
    setup_script = (REPO_ROOT / "setup-hermes.sh").read_text(encoding="utf-8").lower()
    assert "developer/source-checkout path" in setup_script


def test_source_checkout_runtime_override_is_applied_for_local_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTE_CODEX_RUNTIME_BIN", raising=False)
    monkeypatch.setattr(
        "hermes_cli.runtime_override.load_release_install_manifest",
        lambda project_root=None: None,
    )
    monkeypatch.setattr(
        "hermes_cli.runtime_override.expected_vendored_runtime_binary_path",
        lambda project_root=None: tmp_path / "kernel/codex/release/artifacts/linux-x86_64/codex",
    )
    monkeypatch.setattr(
        "hermes_cli.runtime_override.shutil.which",
        lambda cmd: "/opt/codex/bin/codex" if cmd == "codex" else None,
    )

    runtime = apply_source_checkout_runtime_override(REPO_ROOT)

    assert runtime == "/opt/codex/bin/codex"
    assert os.environ["MENTE_CODEX_RUNTIME_BIN"] == "/opt/codex/bin/codex"


def test_main_applies_source_checkout_runtime_override_before_dispatch(monkeypatch, tmp_path):
    import hermes_cli.main as main_mod

    monkeypatch.delenv("MENTE_CODEX_RUNTIME_BIN", raising=False)
    monkeypatch.setattr(main_mod, "cmd_version", lambda args: None)
    monkeypatch.setattr(main_mod, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(main_mod.sys, "argv", ["mente", "--version"])
    monkeypatch.setattr(
        "hermes_cli.runtime_override.load_release_install_manifest",
        lambda project_root=None: None,
    )
    monkeypatch.setattr(
        "hermes_cli.runtime_override.expected_vendored_runtime_binary_path",
        lambda project_root=None: tmp_path / "kernel/codex/release/artifacts/linux-x86_64/codex",
    )
    monkeypatch.setattr(
        "hermes_cli.runtime_override.shutil.which",
        lambda cmd: "/opt/codex/bin/codex" if cmd == "codex" else None,
    )

    main_mod.main()

    assert os.environ["MENTE_CODEX_RUNTIME_BIN"] == "/opt/codex/bin/codex"
