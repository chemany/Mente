from hermes_cli.oneshot import run_oneshot


def test_run_oneshot_routes_through_mente(monkeypatch, capsys):
    monkeypatch.setattr(
        "hermes_cli.oneshot._run_mente",
        lambda prompt, model=None, provider=None: "via mente",
    )
    rc = run_oneshot("inspect repo")
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "via mente\n"
