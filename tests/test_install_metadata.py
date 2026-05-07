"""Regression tests for Mente-first installer defaults."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_install_sh_defaults_to_mente_paths_and_command():
    content = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert 'curl -fsSL https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.sh | bash' in content
    assert 'REPO_URL_SSH="git@github.com:chemany/Mente.git"' in content
    assert 'REPO_URL_HTTPS="https://github.com/chemany/Mente.git"' in content
    assert 'INSTALL_DIR="$MENTE_HOME/mente-agent"' in content
    assert '/usr/local/lib/mente-agent' in content
    assert '/usr/local/bin/mente' in content
    assert 'MENTE_SETUP_SKIP_AUTO_CHAT=1 HERMES_SETUP_SKIP_AUTO_CHAT=1 \\' in content
    assert 'Trying HTTPS clone...' in content
    assert '--with-node-deps' in content
    assert '--china' in content
    assert '--source-tarball PATH' in content
    assert 'Skipping Node.js/browser dependency install during bootstrap' in content
    assert 'Trying local bundled source...' in content
    assert 'Auto-detecting whether China mirrors are needed' in content
    assert 'switching to China mirrors' in content
    assert 'China mode enabled' in content
    assert 'hermes-install-autostash' not in content


def test_install_ps1_defaults_to_mente_paths_and_command():
    content = (REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert '$env:MENTE_HOME' in content
    assert '$env:MENTE_INSTALL_DIR' in content
    assert 'Join-Path $MenteHome "mente-agent"' in content
    assert '$env:MENTE_SETUP_SKIP_AUTO_CHAT = "1"' in content
    assert '$env:HERMES_SETUP_SKIP_AUTO_CHAT = "1"' in content
    assert 'Trying HTTPS clone...' in content
    assert '-WithNodeDeps' in content
    assert '-China' in content
    assert '-SourceTarball' in content
    assert 'Skipping Node.js/browser dependency install during bootstrap' in content
    assert 'Trying local bundled source...' in content
    assert 'Auto-detecting whether China mirrors are needed' in content
    assert 'switching to China mirrors' in content
    assert 'China mode enabled' in content
    assert 'mente command ready' in content
