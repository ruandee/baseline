import copy
import json

import pytest

from scripts import load_baseline_demo as loader
from scripts.prepare_baseline_storylines import build_storylines


def test_explicit_presentations_preserve_authored_values_and_reveal_different_cutoffs():
    manifest = build_storylines()
    original = copy.deepcopy(manifest)
    residents = manifest["residents"]
    assert sum(len(loader.selected_checks(r, "all-history")) for r in residents) == 360
    assert sum(len(loader.selected_checks(r, "scenario-snapshots")) for r in residents) == 353
    assert [loader.selected_checks(r, "scenario-snapshots")[-1]["day"]
            for r in residents[:3]] == [27, 27, 29]
    assert manifest == original


@pytest.mark.parametrize("mutation", ["real", "source", "nan", "missing_feature", "naive_time"])
def test_loader_rejects_scope_and_measurement_changes_before_any_database_work(mutation):
    manifest = build_storylines()
    if mutation == "real":
        manifest["residents"][0]["synthetic"] = False
    elif mutation == "source":
        manifest["residents"][0]["sources"][0]["source_system"] = "external-provider"
    elif mutation == "nan":
        manifest["residents"][0]["checks"][0]["features"]["speech_rate_wpm"] = float("nan")
    elif mutation == "missing_feature":
        del manifest["residents"][0]["checks"][0]["features"]["speech_rate_wpm"]
    else:
        manifest["residents"][0]["checks"][0]["ts"] = "2026-10-17T14:00:00"
    with pytest.raises(loader.LoaderError):
        loader.validate_manifest(manifest)


def test_session_token_goes_only_to_ignored_artifact_and_mismatch_has_nonzero_exit(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(loader, "ROOT", tmp_path)
    report = {"matches_spec": False, "checks_loaded": 353}
    session = {"token": "synthetic-test-token-not-a-credential", "patients": []}
    monkeypatch.setattr(loader, "load_demo", lambda **kwargs: (report, session))
    assert loader.main(["--offline", "--presentation", "scenario-snapshots"]) == 1
    output = capsys.readouterr().out
    assert session["token"] not in output
    assert json.loads((tmp_path / "artifacts/baseline-demo/session.json").read_text()) == session


def test_cli_requires_an_explicit_presentation():
    with pytest.raises(SystemExit):
        loader.main(["--offline"])
