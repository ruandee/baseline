import argparse
import time
from uuid import UUID, uuid4

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.domain import SourceInput
from patient_memory.extraction import embed, extract, fact_id, vector_sql
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
            for c in candidates:
                conn.execute(
                    "INSERT INTO facts(id,tenant_id,patient_id,source_id,concept,value,unit,polarity,"
                    "experiencer,event_type,order_id,valid_from,valid_to,quote,start_offset,end_offset,embedding) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                    (fact_id(source["id"], c), identity.tenant_id, job["patient_id"], source["id"],
                     c.concept, c.value, c.unit, c.polarity, c.experiencer, c.event_type, c.order_id,
                     c.valid_from, c.valid_to, c.quote, c.start, c.end, vector_sql(embed(c.quote))),
                )
            conn.execute("UPDATE sources SET canonical_text=%s,published_at=coalesce(published_at,clock_timestamp()) WHERE id=%s",
                         (canonical, source["id"]))
            # Structured contradictions only; do not guess semantic contradictions in free text.
            conn.execute(
                "INSERT INTO relations SELECT a.tenant_id,a.patient_id,a.id,b.id,'contradicts' "
                "FROM facts a JOIN facts b ON a.tenant_id=b.tenant_id AND a.patient_id=b.patient_id "
                "AND a.concept=b.concept AND a.id>b.id AND a.source_id<>b.source_id "
                "WHERE a.patient_id=%s AND a.concept<>'source_assertion' AND a.order_id IS NULL "
                "AND b.order_id IS NULL AND (a.value<>b.value OR a.polarity<>b.polarity) "
                "AND (a.valid_to IS NULL OR b.valid_from IS NULL OR a.valid_to>=b.valid_from) "
                "AND (b.valid_to IS NULL OR a.valid_from IS NULL OR b.valid_to>=a.valid_from) "
                "ON CONFLICT DO NOTHING", (job["patient_id"],),
            )
            conn.execute("UPDATE jobs SET status='completed',stage='published',lease_until=NULL,error_code=NULL "
                         "WHERE id=%s", (job["id"],))
            bump(conn, job["patient_id"])
            audit(conn, identity, job["patient_id"], "publish", uuid4())
    except Exception as exc:
        permanent = isinstance(exc, ValueError)
        with transaction(cfg, identity) as conn:
            conn.execute(
                "UPDATE jobs SET status=%s,error_code=%s,lease_until=NULL,"
                "next_attempt_at=now()+(%s * interval '1 second') WHERE id=%s AND lease_token=%s",
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
