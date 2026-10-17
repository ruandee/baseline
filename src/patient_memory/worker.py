import argparse
import time
from uuid import UUID, uuid4

from patient_memory.auth import Identity
from patient_memory.baseline.context import store_tags, structured_tags
from patient_memory.config import Settings
from patient_memory.domain import SourceInput
from patient_memory.extraction import extract, store_facts, store_relations
from patient_memory.ingestion import bump, claim_job, lock_patient
from patient_memory.objects import ObjectStore
from patient_memory.storage import audit, transaction


def run_once(cfg: Settings, identity: Identity, objects=None):
    objects = objects or ObjectStore(cfg)
    from patient_memory.lifecycle import purge_once
    if purge_once(cfg, identity, objects):
        return True
    with transaction(cfg, identity) as conn:
        job = claim_job(conn)
        if not job:
            return False
        source = conn.execute("SELECT * FROM sources WHERE id=%s", (job["source_id"],)).fetchone()
    try:
        raw = objects.get(source["object_key"], source["payload_hash"])
        payload = SourceInput.model_validate_json(raw)
        canonical, candidates = extract(payload)
        with transaction(cfg, identity) as conn:
            lock_patient(conn, job["patient_id"])
            current = conn.execute("SELECT * FROM jobs WHERE id=%s FOR UPDATE", (job["id"],)).fetchone()
            if not current or current["lease_token"] != job["lease_token"] or current["status"] != "processing":
                return True
            source = conn.execute("SELECT * FROM sources WHERE id=%s", (job["source_id"],)).fetchone()
            if not source or source["retracted_at"] or source["purged_at"]:
                conn.execute("UPDATE jobs SET status='cancelled',stage='cancelled' WHERE id=%s", (job["id"],))
                return True
            store_facts(conn, identity.tenant_id, job["patient_id"], source["id"], candidates)
            store_tags(conn, identity.tenant_id, job["patient_id"], source["id"],
                       structured_tags(payload, candidates))
            conn.execute("UPDATE sources SET canonical_text=%s,published_at=coalesce(published_at,clock_timestamp()) WHERE id=%s",
                         (canonical, source["id"]))
            store_relations(conn, job["patient_id"])
            conn.execute("UPDATE jobs SET status='completed',stage='published',lease_until=NULL,error_code=NULL "
                         "WHERE id=%s", (job["id"],))
            bump(conn, job["patient_id"])
            audit(conn, identity, job["patient_id"], "publish", uuid4())
    except Exception as exc:
        permanent = isinstance(exc, ValueError)
        with transaction(cfg, identity) as conn:
            conn.execute(
                "UPDATE jobs SET status=%s,error_code=%s,lease_until=NULL,"
                "next_attempt_at=now()+(%s * interval '1 second') WHERE id=%s AND lease_token=%s "
                "AND status='processing'",
                ("failed" if permanent or job["attempt"] >= 5 else "queued",
                 "invalid_extraction" if permanent else "dependency_unavailable",
                 2 ** min(job["attempt"], 5), job["id"], job["lease_token"]),
            )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--actor", type=UUID, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    cfg = Settings()
    identity = Identity(args.actor, args.tenant)
    while True:
        worked = run_once(cfg, identity)
        if args.once:
            return
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
