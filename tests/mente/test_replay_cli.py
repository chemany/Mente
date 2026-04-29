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


def test_replay_cli_accepts_live_eval_flags():
    parser = build_replay_parser()
    args = parser.parse_args(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--live-eval-suite",
            "tests/mente/fixtures/live_eval/gateway_memory_smoke.json",
            "--api-base-url",
            "http://127.0.0.1:8642",
            "--api-key",
            "dev-key",
        ]
    )

    assert args.live_eval_suite.endswith("gateway_memory_smoke.json")
    assert args.api_base_url == "http://127.0.0.1:8642"
    assert args.api_key == "dev-key"


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


def test_replay_cli_writes_normalized_benchmark_report(tmp_path):
    suite_path = Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    output_path = tmp_path / "report.json"

    exit_code = main(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--benchmark-suite",
            str(suite_path),
            "--output-report",
            str(output_path),
        ]
    )

    raw_output = output_path.read_text(encoding="utf-8")
    report = json.loads(raw_output)

    assert exit_code == 0
    assert raw_output.endswith("\n")
    assert [
        (run["case_id"], run["policy_variant"])
        for run in report["runs"]
    ] == sorted(
        (run["case_id"], run["policy_variant"])
        for run in report["runs"]
    )


def test_replay_cli_live_eval_prints_json_report(monkeypatch, capsys):
    seen_requests = []

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _fake_request(method, url, **kwargs):
        seen_requests.append((method, url, kwargs))
        if url.endswith("/v1/responses"):
            return _FakeResponse({"id": f"resp_{len(seen_requests)}"})
        if url.endswith("/api/debug/tasks"):
            return _FakeResponse(
                {
                    "tasks": [
                        {
                            "task_id": "t2",
                            "task_type": "conversation",
                            "metadata": {
                                "source": "gateway",
                                "memory_policy": {"policy_id": "gateway:conversation"},
                                "memory_context": {
                                    "prompt_budget_char_count": 320,
                                    "selected": [
                                        {"memory_id": "mem_gateway_preference_1"}
                                    ],
                                },
                                "memory_promotion": {
                                    "promoted_memory_ids": ["mem_gateway_preference_1"]
                                },
                            },
                        },
                        {
                            "task_id": "t1",
                            "task_type": "conversation",
                            "metadata": {"source": "gateway"},
                        },
                    ]
                }
            )
        if url.endswith("/api/debug/memories"):
            return _FakeResponse(
                {
                    "memories": [
                        {
                            "memory_id": "mem_gateway_preference_1",
                            "source": "gateway",
                            "scope": "session",
                        }
                    ]
                }
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr("mente.testing.live_eval.requests.request", _fake_request)

    exit_code = main(
        [
            "tests/mente/fixtures/replay/gateway_conversation.json",
            "--live-eval-suite",
            "tests/mente/fixtures/live_eval/gateway_memory_smoke.json",
            "--api-base-url",
            "http://127.0.0.1:8642",
            "--api-key",
            "dev-key",
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["suite_id"] == "gateway_memory_smoke"
    assert report["summary"]["pass_count"] == 1
    assert report["cases"][0]["status"] == "pass"
    assert [method for method, _, _ in seen_requests] == ["POST", "POST", "GET", "GET"]
