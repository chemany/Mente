from pathlib import Path

from mente.testing.live_eval import evaluate_live_eval_case, load_live_eval_suite


def test_load_live_eval_suite_parses_cases():
    suite = load_live_eval_suite(
        Path("tests/mente/fixtures/live_eval/gateway_memory_smoke.json")
    )

    assert suite.suite_id == "gateway_memory_smoke"
    assert suite.cases[0].case_id == "session_preference_roundtrip"
    assert len(suite.cases[0].turns) == 2
    assert suite.cases[0].acceptance.min_task_count == 2


def test_evaluate_live_eval_case_scores_acceptance():
    case = load_live_eval_suite(
        Path("tests/mente/fixtures/live_eval/gateway_memory_smoke.json")
    ).cases[0]
    task_page = {
        "tasks": [
            {
                "task_id": "t1",
                "task_type": "conversation",
                "metadata": {"source": "gateway"},
            },
            {
                "task_id": "t2",
                "task_type": "conversation",
                "metadata": {"source": "gateway"},
            },
        ]
    }
    memory_page = {
        "memories": [
            {"memory_id": "mem_gateway_preference_1", "source": "gateway", "scope": "session"}
        ]
    }
    execution_trace = {
        "policy_id": "gateway:conversation",
        "prompt_budget_char_count": 320,
        "selected_memory_ids": ["mem_gateway_preference_1"],
        "promoted_memory_ids": ["mem_gateway_preference_1"],
    }

    report = evaluate_live_eval_case(case, task_page, memory_page, execution_trace)

    assert report["status"] == "pass"
    assert report["score"] == 1.0
