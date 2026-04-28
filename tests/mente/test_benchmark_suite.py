from pathlib import Path

from mente.testing.benchmark import load_benchmark_suite, run_benchmark_suite


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
