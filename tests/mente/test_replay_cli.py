from mente.testing.cli import build_replay_parser


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
