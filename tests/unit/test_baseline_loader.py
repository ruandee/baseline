import copy
import json
from contextlib import contextmanager

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


@pytest.mark.parametrize("mutation", ["unlisted", "version", "hash", "payload"])
def test_same_source_system_never_authorizes_extra_documents_or_changed_payloads(mutation):
    resident = build_storylines()["residents"][0]
    payload = loader.SourceInput.model_validate(resident["sources"][0]).model_dump(mode="json")
    row = {"payload": payload, "external_version": payload["external_version_id"],
           "payload_hash": loader.digest(payload)}
    loader.validate_existing_sources([row], resident)
    if mutation == "unlisted":
        payload["external_document_id"] = "extra-context-same-synthetic-system"
        row["payload_hash"] = loader.digest(payload)
    elif mutation == "version":
        row["external_version"] = "synthetic-v2"
    elif mutation == "hash":
        row["payload_hash"] = "0" * 64
    else:
        payload["records"][0]["value"] = "changed synthetic value"
    with pytest.raises(loader.LoaderError, match="unlisted or conflicting"):
        loader.validate_existing_sources([row], resident)


@pytest.mark.parametrize("mutation,verified", [(None, True), ("unrelated_quote", False),
                                             ("unrelated_fact", False), ("bad_fact_span", False)])
def test_context_verification_requires_expected_phrase_in_tag_and_exact_covering_fact(
        monkeypatch, mutation, verified):
    canonical = "Quiet at lunch, didn't finish her soup."
    row = {"canonical_text": canonical, "quote": canonical, "start_offset": 0,
           "end_offset": len(canonical), "fact_id": "synthetic-fact", "fact_quote": canonical,
           "fact_start": 0, "fact_end": len(canonical)}
    if mutation == "unrelated_quote":
        row.update(quote="Quiet at lunch", end_offset=14)
    elif mutation == "unrelated_fact":
        row.update(fact_quote="Quiet at lunch", fact_end=14)
    elif mutation == "bad_fact_span":
        row["fact_quote"] = "invented source text"

    class Connection:
        def execute(self, *args):
            return self

        def fetchall(self):
            return [row]

    @contextmanager
    def transaction(*args):
        yield Connection()

    monkeypatch.setattr(loader, "transaction", transaction)
    monkeypatch.setattr(loader, "patient_access", lambda *a, **k: None)
    resident = {"id": "synthetic-test", "expected_context": [{"tag": "poor_intake",
                "quote": "didn't finish her soup", "source_document_id": "synthetic-note"}]}
    report = loader._context_report(None, loader.DemoScope(), [resident])
    assert report[0]["exact_span_verified"] is verified
