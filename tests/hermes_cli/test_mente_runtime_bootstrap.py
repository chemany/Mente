"""Regression tests for Mente-first bootstrap surfaces."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_install_sh_symlinks_mente_as_primary_command():
    content = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert 'ln -sf "$MENTE_BIN" "$command_link_dir/mente"' in content
    assert 'ln -sf "$MENTE_BIN" "$command_link_dir/hermes"' not in content


def test_setup_script_brands_itself_as_mente():
    content = (REPO_ROOT / "setup-hermes.sh").read_text(encoding="utf-8")

    assert "Mente Agent Setup Script" in content
    assert "⚕ Mente Agent Setup" in content
