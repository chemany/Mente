from hermes_cli.oneshot import run_oneshot


def test_run_oneshot_routes_through_mente(monkeypatch, capsys):
    bootstrap_calls = []
    monkeypatch.setattr(
        "hermes_cli.oneshot.bootstrap_mente_home",
        lambda: bootstrap_calls.append(True),
    )
    monkeypatch.setattr(
        "hermes_cli.oneshot._run_mente",
        lambda prompt, model=None, provider=None: "via mente",
    )
    rc = run_oneshot("inspect repo")
    captured = capsys.readouterr()
    assert rc == 0
    assert bootstrap_calls == [True]
    assert captured.out == "via mente\n"
