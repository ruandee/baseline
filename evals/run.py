"""Reproducible retrieval/evidence evaluation against an authored synthetic corpus."""
import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import psycopg

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.domain import SourceInput, now
from patient_memory.generation import ExtractiveGenerator, build_answer
from patient_memory.ingestion import submit
from patient_memory.objects import ObjectStore
from patient_memory.retrieval import retrieve
from patient_memory.storage import transaction
from patient_memory.worker import run_once

CORPUS = Path(__file__).resolve().parents[1] / "fixtures/synthetic/corpus.json"


def fixture_identity(cfg, run_id, tenant_number):
    tenant = uuid5(NAMESPACE_URL, f"synthetic-eval/{run_id}/{tenant_number}")
    actor = uuid5(tenant, "importer")
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO tenants VALUES(%s,'synthetic-eval') ON CONFLICT DO NOTHING", (tenant,))
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-eval-importer') "
                     "ON CONFLICT DO NOTHING", (actor, tenant))
    return Identity(actor, tenant)


def load_profile(cfg, objects, identity, profile):
    patient = uuid5(identity.tenant_id, profile["id"])
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                     (patient, identity.tenant_id, profile["id"]))
        conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'importer',true) ON CONFLICT DO NOTHING",
                     (identity.tenant_id, patient, identity.principal_id))
    sources = {}
    base = {"external_version_id": "1", "source_system": "synthetic-eval",
            "recorded_at": "2026-01-02T08:00:00Z", "effective_from": "2026-01-02T07:00:00Z"}
    for topic in ["sleep", "pain", "mobility", "hydration"]:
        payload = {**base, "external_document_id": topic}
        if topic in {"sleep", "mobility"}:
            payload.update(kind="observation", author_role="system",
                           records=[{"concept": topic, "value": profile[topic]}])
        else:
            payload.update(kind="patient_report" if topic == "pain" else "nursing_note",
                           author_role="patient" if topic == "pain" else "nurse", text=profile[topic])
        source = SourceInput.model_validate(payload)
        with transaction(cfg, identity) as conn:
            job = submit(conn, identity, patient, source, f"fixture-{topic}", objects)
        run_once(cfg, identity, objects)
        sources[topic] = job["source_version_id"]
    return patient, sources


def evaluate(cfg=None, output="artifacts/eval.json", split="all"):
    cfg = cfg or Settings()
    objects = ObjectStore(cfg)
    objects.initialize()
    manifest_bytes = CORPUS.read_bytes()
    corpus = json.loads(manifest_bytes)
    run_id = uuid4()
    identities = [fixture_identity(cfg, run_id, i) for i in range(2)]
    outcomes, latencies = [], []
    generator = ExtractiveGenerator()
    for i, profile in enumerate(corpus["profiles"]):
        if split != "all" and profile["split"] != split:
            continue
        identity = identities[i % 2]
        patient, sources = load_profile(cfg, objects, identity, profile)
        for question, gold in profile["questions"]:
            known = now()
            from datetime import datetime
            as_of = datetime.fromisoformat("2026-01-03T00:00:00+00:00")
            started = time.perf_counter()
            with transaction(cfg, identity) as conn:
                revision = conn.execute("SELECT revision FROM patients WHERE id=%s", (patient,)).fetchone()["revision"]
                facts, coverage = retrieve(conn, patient, as_of, known, question)
            latencies.append((time.perf_counter() - started) * 1000)
            answer = build_answer(generator, question, facts, coverage, patient, revision, as_of, known)
            expected = sources[gold] if gold else None
            matched = expected in {str(e.source_version_id) for e in answer.evidence} if expected else not answer.claims
            valid = all(str(e.source_version_id) in sources.values() for e in answer.evidence)
            outcomes.append({"profile": profile["id"], "split": profile["split"], "question": question,
                             "gold_topic": gold, "gold_source_id": expected, "passed": matched,
                             "isolation_passed": valid, "claims": len(answer.claims),
                             "status": answer.status, "retrieved_source_ids": [str(e.source_version_id) for e in answer.evidence]})
    known_cases = [o for o in outcomes if o["gold_topic"]]
    unknown_cases = [o for o in outcomes if not o["gold_topic"]]
    metrics = {
        "gold_source_recall_at_12": {"numerator": sum(o["passed"] for o in known_cases), "denominator": len(known_cases)},
        "appropriate_abstention": {"numerator": sum(o["passed"] for o in unknown_cases), "denominator": len(unknown_cases)},
        "patient_scope": {"numerator": sum(o["isolation_passed"] for o in outcomes), "denominator": len(outcomes)},
        "retrieval_latency_ms": {"median": statistics.median(latencies), "p95": sorted(latencies)[int(0.95 * (len(latencies)-1))]},
        "human_claim_support": None,
        "temporal_correctness": "Separate integration/e2e regression cases; not measured by these 60 questions",
    }
    report = {"suite": corpus["version"], "corpus_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
              "run_id": str(run_id), "provider": "extractive-stub-v1", "embedding": "hash64-v1",
              "split": split, "question_count": len(outcomes), "metrics": metrics, "outcomes": outcomes,
              "limitations": ["Synthetic engineering cases only", "Not a clinical benchmark",
                              "No independent human review", "No real semantic embeddings or live model evaluation",
                              "Latency includes local DB connection; no 10k-note load test"]}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"question_count": len(outcomes), "metrics": metrics, "output": str(path)}, indent=2))
    return all(o["passed"] and o["isolation_passed"] for o in outcomes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["synthetic"], default="synthetic")
    parser.add_argument("--provider", choices=["stub"], default="stub")
    parser.add_argument("--split", choices=["all", "development", "test"], default="all")
    parser.add_argument("--output", default="artifacts/eval.json")
    args = parser.parse_args()
    raise SystemExit(0 if evaluate(output=args.output, split=args.split) else 1)


if __name__ == "__main__":
    main()
