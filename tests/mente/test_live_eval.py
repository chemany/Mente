from pathlib import Path

from mente.testing.live_eval import load_live_eval_suite


def test_load_live_eval_suite_parses_cases():
    suite = load_live_eval_suite(
        Path("tests/mente/fixtures/live_eval/gateway_memory_smoke.json")
    )

    assert suite.suite_id == "gateway_memory_smoke"
    assert suite.cases[0].case_id == "session_preference_roundtrip"
    assert len(suite.cases[0].turns) == 2
    assert suite.cases[0].acceptance.min_task_count == 2
