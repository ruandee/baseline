"""Exercise the running local API, including a correction and a knowledge-time query."""
import argparse
import json
from uuid import uuid4

import httpx

from evals.run import fixture_identity
from patient_memory.auth import synthetic_token
from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.objects import ObjectStore
from patient_memory.worker import run_once


def demo(base_url="http://127.0.0.1:8000"):
    if base_url not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        raise ValueError("Demo is limited to the loopback synthetic API on port 8000")
    cfg = Settings()
    objects = ObjectStore(cfg)
    objects.initialize()
    identity = fixture_identity(cfg, uuid4(), 0)
    # Bootstrap only the synthetic admin flag; subsequent patient writes go through the API.
    import psycopg
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("UPDATE principals SET administrator=true WHERE tenant_id=%s AND id=%s",
                     (identity.tenant_id, identity.principal_id))
    token = synthetic_token(identity, cfg)
    with httpx.Client(base_url=base_url, headers={"Authorization": "Bearer " + token}, timeout=30) as client:
        health = client.get("/v1/health/live")
        health.raise_for_status()
        patient = client.post("/v1/patients", json={"external_id": "synthetic-demo"})
        patient.raise_for_status()
        pid = patient.json()["patient_id"]
        root = f"/v1/patients/{pid}"
        assignment = client.put(root + "/assignments", json={"principal_id": str(identity.principal_id), "role": "importer"})
        assignment.raise_for_status()
        source = {"external_document_id": "synthetic-sleep", "external_version_id": "1",
                  "source_system": "synthetic-demo", "kind": "nursing_note", "author_role": "nurse",
                  "recorded_at": now().isoformat(), "effective_from": "2026-01-01T08:00:00Z",
                  "text": "Patient reports interrupted sleep."}
        first = client.post(root + "/sources", json=source, headers={"Idempotency-Key": "synthetic-original"})
        first.raise_for_status()
        run_once(cfg, identity, objects)
        cutoff = now().isoformat()
        original = client.post(root + "/questions", json={"question": "sleep"})
        original.raise_for_status()
        source.update(external_version_id="2", supersedes_version_id=first.json()["source_version_id"],
                      text="Patient reports improved sleep.")
        amended = client.post(root + "/sources", json=source, headers={"Idempotency-Key": "synthetic-correction"})
        amended.raise_for_status()
        run_once(cfg, identity, objects)
        current = client.post(root + "/questions", json={"question": "sleep"})
        historical = client.post(root + "/questions", json={"question": "sleep", "known_at": cutoff})
        summary = client.post(root + "/summaries", json={"shift_start": "2026-01-01T00:00:00Z", "shift_end": now().isoformat()})
        for response in [current, historical, summary]:
            response.raise_for_status()
        assert original.json()["claims"][0]["text"] == historical.json()["claims"][0]["text"]
        assert original.json()["claims"][0]["text"] != current.json()["claims"][0]["text"]
        result = {"patient_id": pid, "mode": "synthetic", "model": current.json()["versions"]["model"],
                  "original": original.json(), "current": current.json(),
                  "historical": historical.json(), "summary": summary.json()}
        print(json.dumps(result, indent=2))
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    demo(parser.parse_args().base_url)
