import json
from pathlib import Path

from mente.testing.benchmark import (
    load_benchmark_suite,
    run_benchmark_suite,
    write_benchmark_baseline,
)
from mente.testing.cli import build_replay_parser, main


def test_replay_cli_accepts_fixture_path():
    parser = build_replay_parser()
    args = parser.parse_args(["tests/mente/fixtures/replay/gateway_conversation.json"])
    assert args.fixture_path.endswith("gateway_conversation.json")


def test_replay_cli_accepts_compare_memory_flag():
    parser = build_replay_parser()
    args = parser.parse_args(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--compare-memory",
        ]
    )
    assert args.compare_memory is True


def test_replay_cli_accepts_show_prompt_metrics_flag():
    parser = build_replay_parser()
    args = parser.parse_args(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--compare-memory",
            "--show-prompt-metrics",
        ]
    )
    assert args.show_prompt_metrics is True


def test_replay_cli_accepts_benchmark_suite_flag():
    parser = build_replay_parser()
    args = parser.parse_args(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--benchmark-suite",
            "tests/mente/fixtures/benchmarks/memory_policy_smoke.json",
        ]
    )
    assert args.benchmark_suite.endswith("memory_policy_smoke.json")


def test_replay_cli_accepts_benchmark_baseline_flags():
    parser = build_replay_parser()
    args = parser.parse_args(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--benchmark-suite",
            "tests/mente/fixtures/benchmarks/memory_policy_smoke.json",
            "--baseline",
            "tests/mente/fixtures/benchmarks/memory_policy_smoke.baseline.json",
            "--write-baseline",
            "tmp.baseline.json",
            "--output-report",
            "tmp.report.json",
            "--fail-on-regression",
        ]
    )

    assert args.baseline.endswith("memory_policy_smoke.baseline.json")
    assert args.write_baseline == "tmp.baseline.json"
    assert args.output_report == "tmp.report.json"
    assert args.fail_on_regression is True


def test_replay_cli_fails_on_benchmark_regression(tmp_path):
    suite_path = Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    output_path = tmp_path / "comparison.json"
    baseline_path = tmp_path / "baseline.json"

    suite = load_benchmark_suite(suite_path)
    baseline = run_benchmark_suite(suite)
    baseline["runs"][0]["status"] = "pass"
    baseline["runs"][0]["score"] = baseline["runs"][0]["score"] + 0.5
    write_benchmark_baseline(baseline, baseline_path)

    exit_code = main(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--benchmark-suite",
            str(suite_path),
            "--baseline",
            str(baseline_path),
            "--output-report",
            str(output_path),
            "--fail-on-regression",
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["summary"]["regression_count"] >= 1
