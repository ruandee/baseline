"""The actual hosted entrypoint must run scheduling and retention under the right tenant."""
import json

import pytest

from patient_memory import worker
from patient_memory.auth import Identity
from patient_memory.config import Settings
from scripts import hosted_demo
from scripts.prepare_deployment import initialize, store_credentials
from scripts.seed import uid


@pytest.mark.parametrize("command,actor,tenant", [
    ("worker", "0/importer", "tenant-0"),
    ("kaze-worker", "kaze-demo/service", "kaze-demo"),
])
def test_hosted_workers_delegate_to_shared_loop_without_admin(monkeypatch, command, actor, tenant):
    cfg = Settings(admin_database_url="")
    called = []
    monkeypatch.setattr(hosted_demo, "deployment_settings", lambda: cfg)
    monkeypatch.setattr(worker, "run_worker", lambda settings, identity: called.append(
        (settings, identity)))
    monkeypatch.setattr("sys.argv", ["hosted_demo", command])
    hosted_demo.main()
    assert called == [(cfg, Identity(uid(actor), uid(tenant)))]


def test_shared_loop_repeats_scheduler_and_retention_even_when_no_ingestion(monkeypatch):
    cfg = Settings(admin_database_url="")
    identity = Identity(uid("kaze-demo/service"), uid("kaze-demo"))
    events = []
    clock = [0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker, "sender_from_settings", lambda cfg: "stub-sender")
    monkeypatch.setattr(worker, "retire_sessions", lambda cfg, who: events.append(
        ("retire", clock[0], who)))
    monkeypatch.setattr(worker, "run_pass", lambda cfg, who, sender: events.append(
        ("schedule", clock[0], who, sender)))
    monkeypatch.setattr(worker, "run_once", lambda cfg, who: False)

    def sleep(seconds):
        clock[0] += seconds
        if clock[0] > 60:
            raise SystemExit

    monkeypatch.setattr(worker.time, "sleep", sleep)
    with pytest.raises(SystemExit):
        worker.run_worker(cfg, identity)
    assert [(e[0], e[1]) for e in events] == [
        ("retire", 0), ("schedule", 0), ("schedule", 15), ("schedule", 30),
        ("schedule", 45), ("retire", 60), ("schedule", 60)]
    assert all(e[2] == identity for e in events)
    assert all(e[3] == "stub-sender" for e in events if e[0] == "schedule")


def test_private_bootstrap_omits_service_token_and_preserves_explicit_consent_option(
        monkeypatch, tmp_path, capsys):
    import scripts.kaze_demo as bootstrap

    called = []
    def fake(cfg, *, grant_consent):
        called.append(grant_consent)
        return {"tenant_id": "fictional", "service": {"token": "NEVER_EXPORT"},
                "people": [{"patient_id": "fictional", "token": "person-token"}]}

    monkeypatch.setattr(bootstrap, "kaze_demo", fake)
    destination = tmp_path / "private" / "session.json"
    hosted_demo.bootstrap_kaze(Settings(), destination=destination)
    hosted_demo.bootstrap_kaze(Settings(), grant_consent=True, destination=destination)
    assert called == [False, True]
    assert "NEVER_EXPORT" not in destination.read_text()
    assert set(json.loads(destination.read_text())) == {"tenant_id", "people"}
    assert capsys.readouterr().out == ""


def test_kaze_credentials_do_not_replace_the_nurse_or_psw_token(tmp_path):
    env = tmp_path / ".env.demo"
    initialize(env, "demo.example.com")
    store_credentials(env, {"nurse": "aaa.bbb.ccc", "psw": "ddd.eee.fff"})
    store_credentials(env, {"kaze": "ggg.hhh.iii", "kaze_patient_id": str(uid("kaze-person"))},
                      kaze=True)
    values = dict(line.split("=", 1) for line in env.read_text().splitlines()
                  if line and not line.startswith("#"))
    assert values["PM_DEMO_TOKEN"] == "aaa.bbb.ccc"
    assert values["PM_DEMO_PSW_TOKEN"] == "ddd.eee.fff"
    assert values["PM_DEMO_KAZE_TOKEN"] == "ggg.hhh.iii"
    assert values["PM_DEMO_KAZE_PATIENT_ID"] == str(uid("kaze-person"))
