from unittest.mock import MagicMock, patch

import cron.scheduler as cron_scheduler


def test_run_job_routes_to_mente_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_CRON_EXECUTOR", "mente")

    job = {
        "id": "mente-job",
        "name": "Mente Job",
        "prompt": "say hello",
    }
    fake_db = MagicMock()

    with patch("cron.scheduler._hermes_home", tmp_path), \
         patch("cron.scheduler._resolve_origin", return_value=None), \
         patch("dotenv.load_dotenv"), \
         patch("hermes_state.SessionDB", return_value=fake_db), \
         patch(
             "hermes_cli.runtime_provider.resolve_runtime_provider",
             return_value={
                 "api_key": "test-key",
                 "base_url": "https://example.invalid/v1",
                 "provider": "openrouter",
                 "api_mode": "chat_completions",
             },
         ), \
         patch(
             "cron.scheduler._run_mente_cron_job",
             return_value=(True, "# Cron Job: Mente Job\n", "via mente", None),
             create=True,
         ) as mente_mock, \
         patch("run_agent.AIAgent") as legacy_agent_cls:
        success, output, final_response, error = cron_scheduler.run_job(job)

    assert success is True
    assert output == "# Cron Job: Mente Job\n"
    assert final_response == "via mente"
    assert error is None
    mente_mock.assert_called_once()
    assert mente_mock.call_args.kwargs["job"] == job
    assert "say hello" in mente_mock.call_args.kwargs["prompt"]
    assert mente_mock.call_args.kwargs["session_id"].startswith("cron_mente-job_")
    legacy_agent_cls.assert_not_called()
