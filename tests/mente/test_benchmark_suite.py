from pathlib import Path

from mente.testing.benchmark import (
    compare_benchmark_report_to_baseline,
    load_benchmark_baseline,
    load_benchmark_suite,
    run_benchmark_suite,
    write_benchmark_baseline,
)


def test_load_benchmark_suite_parses_policy_variants_and_cases():
    suite = load_benchmark_suite(
        Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    )

    assert suite.suite_id == "memory_policy_smoke"
    assert set(suite.policy_variants) == {"tight_gateway", "balanced_gateway"}
    assert suite.cases[0].case_id == "gateway_pref_concise"
    assert suite.cases[0].expectations["tight_gateway"].memory_fact_count == 1


def test_run_benchmark_suite_scores_cases():
    suite = load_benchmark_suite(
        Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    )

    report = run_benchmark_suite(suite)

    assert report["suite_id"] == "memory_policy_smoke"
    assert report["summary"]["case_count"] == 1
    assert report["summary"]["policy_run_count"] == 2
    assert report["summary"]["pass_count"] >= 1
    assert report["runs"][0]["checks"]


def test_write_and_load_benchmark_baseline_round_trips(tmp_path):
    suite = load_benchmark_suite(
        Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    )
    report = run_benchmark_suite(suite)
    baseline_path = tmp_path / "memory_policy_smoke.baseline.json"

    write_benchmark_baseline(report, baseline_path)
    loaded = load_benchmark_baseline(baseline_path)

    assert loaded["suite_id"] == "memory_policy_smoke"
    assert loaded["summary"]["policy_run_count"] == 2
    assert [
        (run["case_id"], run["policy_variant"])
        for run in loaded["runs"]
    ] == sorted(
        (run["case_id"], run["policy_variant"])
        for run in loaded["runs"]
    )


def test_compare_benchmark_report_to_baseline_detects_regressions():
    suite = load_benchmark_suite(
        Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    )
    current = run_benchmark_suite(suite)
    baseline = run_benchmark_suite(suite)

    baseline["runs"][0]["status"] = "pass"
    baseline["runs"][0]["score"] = 1.0
    current["runs"][0]["status"] = "fail"
    current["runs"][0]["score"] = 0.5

    comparison = compare_benchmark_report_to_baseline(current, baseline)
    comparison_run = next(
        run
        for run in comparison["runs"]
        if run["case_id"] == baseline["runs"][0]["case_id"]
        and run["policy_variant"] == baseline["runs"][0]["policy_variant"]
    )

    assert comparison["summary"]["regression_count"] >= 1
    assert comparison["summary"]["status"] == "regression"
    assert comparison_run["is_regression"] is True
    assert "status_degraded" in comparison_run["reasons"]
    assert "score_decreased" in comparison_run["reasons"]


def test_compare_benchmark_report_to_baseline_treats_new_runs_as_neutral():
    baseline = {
        "suite_id": "suite_1",
        "summary": {
            "case_count": 1,
            "policy_run_count": 1,
            "pass_count": 1,
            "fail_count": 0,
            "average_score": 1.0,
        },
        "runs": [
            {
                "case_id": "case_1",
                "policy_variant": "tight",
                "status": "pass",
                "score": 1.0,
                "checks": {},
                "result": {},
            }
        ],
    }
    current = {
        **baseline,
        "summary": {
            **baseline["summary"],
            "policy_run_count": 2,
        },
        "runs": [
            *baseline["runs"],
            {
                "case_id": "case_1",
                "policy_variant": "balanced",
                "status": "pass",
                "score": 1.0,
                "checks": {},
                "result": {},
            },
        ],
    }

    comparison = compare_benchmark_report_to_baseline(current, baseline)

    assert comparison["summary"]["new_run_count"] == 1
    assert comparison["summary"]["regression_count"] == 0


def test_benchmark_baseline_round_trip_matches_compare_path(tmp_path):
    suite = load_benchmark_suite(
        Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    )
    report = run_benchmark_suite(suite)
    baseline_path = tmp_path / "baseline.json"
    write_benchmark_baseline(report, baseline_path)

    loaded = load_benchmark_baseline(baseline_path)
    comparison = compare_benchmark_report_to_baseline(report, loaded)

    assert comparison["summary"]["regression_count"] == 0
    assert comparison["summary"]["status"] == "unchanged"
