from pathlib import Path

from mente.testing.benchmark import load_benchmark_suite


def test_load_benchmark_suite_parses_policy_variants_and_cases():
    suite = load_benchmark_suite(
        Path("tests/mente/fixtures/benchmarks/memory_policy_smoke.json")
    )

    assert suite.suite_id == "memory_policy_smoke"
    assert set(suite.policy_variants) == {"tight_gateway", "balanced_gateway"}
    assert suite.cases[0].case_id == "gateway_pref_concise"
    assert suite.cases[0].expectations["tight_gateway"].memory_fact_count == 1
