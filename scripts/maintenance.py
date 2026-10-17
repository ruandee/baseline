"""Patient-scoped repair and orphan reconciliation for synthetic development."""
import argparse
from datetime import timedelta
from uuid import UUID, uuid4

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.ingestion import lock_patient
from patient_memory.objects import ObjectStore
from patient_memory.storage import audit, patient_access, transaction


def requeue(cfg, actor, patient_id):
    with transaction(cfg, actor) as conn:
        lock_patient(conn, patient_id)
        patient_access(conn, patient_id, write=True)
        rows = conn.execute(
            "UPDATE jobs j SET status='queued',attempt=0,next_attempt_at=now(),lease_token=NULL "
            "FROM sources s WHERE j.tenant_id=s.tenant_id AND j.patient_id=s.patient_id "
            "AND j.source_id=s.id AND j.patient_id=%s AND s.retracted_at IS NULL "
            "AND s.purged_at IS NULL AND j.status IN ('completed','failed') RETURNING j.id", (patient_id,),
        ).fetchall()
        audit(conn, actor, patient_id, "reindex_queued", uuid4())
        return len(rows)


def orphans(cfg, actor, patient_id, delete=False):
    objects = ObjectStore(cfg)
    with transaction(cfg, actor) as conn:
        lock_patient(conn, patient_id)
        patient_access(conn, patient_id, write=True)
        referenced = {r["object_key"] for r in conn.execute(
            "SELECT object_key FROM sources WHERE patient_id=%s", (patient_id,)).fetchall()}
        keys = []
        for page in objects.client.get_paginator("list_objects_v2").paginate(
                Bucket=objects.bucket, Prefix=f"{actor.tenant_id}/{patient_id}/"):
            for obj in page.get("Contents", []):
                if obj["Key"] not in referenced and obj["LastModified"] < now() - timedelta(hours=24):
                    keys.append(obj["Key"])
                    if delete:
                        objects.delete(obj["Key"])
        audit(conn, actor, patient_id, "orphan_delete" if delete else "orphan_report", uuid4())
        return keys


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["reindex", "orphan-report", "orphan-delete"])
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--actor", required=True, type=UUID)
    parser.add_argument("--patient", required=True, type=UUID)
    args = parser.parse_args()
    actor, cfg = Identity(args.actor, args.tenant), Settings()
    print(requeue(cfg, actor, args.patient) if args.action == "reindex" else
          orphans(cfg, actor, args.patient, delete=args.action == "orphan-delete"))
