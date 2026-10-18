"""KAZE capture/state tests use fake clocks, permissions and uploads; no model or SMS calls."""



def test_kaze_bootstrap_cli_writes_ignored_artifact_without_printing_tokens(tmp_path, monkeypatch,
                                                                         capsys):
    from scripts import kaze_demo
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(kaze_demo, "kaze_demo", lambda: {"people": [{"token": "synthetic-token"}]})
    kaze_demo.main()
    output = capsys.readouterr().out
    assert "synthetic-token" not in output
    assert "synthetic-token" in (tmp_path / "artifacts/kaze-demo/session.json").read_text()
