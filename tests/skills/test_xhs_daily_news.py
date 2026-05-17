from __future__ import annotations

import importlib.util
import py_compile
import sys
from pathlib import Path
from types import SimpleNamespace


SKILL_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "social-media"
    / "xhs-daily-news"
    / "scripts"
)
RUN_FULL_WORKFLOW_PATH = SKILL_SCRIPTS_DIR / "run_full_workflow.py"
PUBLISH_TO_XHS_PATH = SKILL_SCRIPTS_DIR / "publish_to_xhs.py"


def load_module(module_name: str, script_path: Path):
    sys.path.insert(0, str(script_path.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(script_path.parent))
        except ValueError:
            pass


def test_run_full_workflow_compiles():
    py_compile.compile(str(RUN_FULL_WORKFLOW_PATH), doraise=True)


def test_run_full_workflow_step_uses_arg_list_without_shell(tmp_path, monkeypatch):
    mod = load_module("xhs_run_full_workflow_test", RUN_FULL_WORKFLOW_PATH)
    input_file = tmp_path / "daily-briefing-2026-04-13.md"
    input_file.write_text("# test\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.step3_convert_to_xhs("2026-04-13", tmp_path) is True
    assert captured["cmd"] == [
        "python3",
        str(SKILL_SCRIPTS_DIR / "convert_to_xhs.py"),
        "--input",
        str(input_file),
        "--output",
        str(tmp_path / "xhs_daily_2026-04-13.md"),
    ]
    assert captured["kwargs"]["shell"] is False
    assert "executable" not in captured["kwargs"]


def test_publish_run_command_uses_arg_list_without_shell(monkeypatch):
    mod = load_module("xhs_publish_to_xhs_test", PUBLISH_TO_XHS_PATH)
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod.run_command(
        ["rednote", "status", "--instance", "seller-main"],
        "检查 rednote 实例状态: seller-main",
    )

    assert result is not None
    assert captured["cmd"] == ["rednote", "status", "--instance", "seller-main"]
    assert captured["kwargs"]["shell"] is False
