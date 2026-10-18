import argparse
import logging
import time
from uuid import UUID, uuid4

import psycopg

from patient_memory.auth import Identity
from patient_memory.baseline.context import store_tags, structured_tags
from patient_memory.baseline.notes import note_tags, publish_note_tags
from patient_memory.baseline.safety import PASS_EVERY_S, run_pass, sender_from_settings
from patient_memory.baseline.sessions import retire as retire_sessions
from patient_memory.baseline.vitals import UNITS as VITAL_CONCEPTS
from patient_memory.baseline.vitals import refresh_vitals
from patient_memory.config import Settings
from patient_memory.domain import SourceInput
from patient_memory.extraction import extract, store_facts, store_relations
from patient_memory.ingestion import bump, claim_job, lock_patient
from patient_memory.objects import ObjectStore
from patient_memory.storage import audit, patient_access, transaction

RETIRE_EVERY_S = 60


def run_once(cfg: Settings, identity: Identity, objects=None):
    objects = objects or ObjectStore(cfg)
    from patient_memory.lifecycle import purge_once
    if purge_once(cfg, identity, objects):
        return True
    with transaction(cfg, identity) as conn:
        job = claim_job(conn)
        if not job:
            return False
        patient_access(conn, job["patient_id"], write=True)
        source = conn.execute("SELECT * FROM sources WHERE id=%s", (job["source_id"],)).fetchone()
    published = False
    try:
        raw = objects.get(source["object_key"], source["payload_hash"])
        payload = SourceInput.model_validate_json(raw)
        canonical, candidates = extract(payload)
        tags, note_method = note_tags(payload, cfg) if payload.kind == "nursing_note" else ([], None)
        with transaction(cfg, identity) as conn:
            lock_patient(conn, job["patient_id"])
            patient_access(conn, job["patient_id"], write=True)
            current = conn.execute("SELECT * FROM jobs WHERE id=%s FOR UPDATE", (job["id"],)).fetchone()
            if not current or current["lease_token"] != job["lease_token"] or current["status"] != "processing":
                return True
            source = conn.execute("SELECT * FROM sources WHERE id=%s", (job["source_id"],)).fetchone()
            if not source or source["retracted_at"] or source["purged_at"] or source["purge_requested"]:
                conn.execute("UPDATE jobs SET status='cancelled',stage='cancelled' WHERE id=%s", (job["id"],))
                return True
            store_facts(conn, identity.tenant_id, job["patient_id"], source["id"], candidates)
            store_tags(conn, identity.tenant_id, job["patient_id"], source["id"],
                       structured_tags(payload, candidates))
            if note_method:
                publish_note_tags(conn, identity, job["patient_id"], source["id"], tags, note_method)
            conn.execute("UPDATE sources SET canonical_text=%s,published_at=coalesce(published_at,clock_timestamp()) WHERE id=%s",
                         (canonical, source["id"]))
            store_relations(conn, job["patient_id"])
            conn.execute("UPDATE jobs SET status='completed',stage='published',lease_until=NULL,error_code=NULL "
                         "WHERE id=%s", (job["id"],))
            bump(conn, job["patient_id"])
            audit(conn, identity, job["patient_id"], "publish", uuid4())
        published = True
        if payload.kind == "observation" and any(
                record.concept in VITAL_CONCEPTS for record in payload.records or []):
            # Source publication commits before acquiring the budget/patient admission locks.
            # The fresh snapshot rechecks authorization, exact sources and current revision.
            with transaction(cfg, identity) as conn:
                result = refresh_vitals(conn, cfg, identity, job["patient_id"])
                audit(conn, identity, job["patient_id"], "vitals_refresh", uuid4(),
                      result="available" if result else "unavailable")
    except Exception as exc:
        permanent = isinstance(exc, ValueError)
        with transaction(cfg, identity) as conn:
            if published:
                # Source success is immutable; expose derivative failure separately, never
                # relabel a successfully published source as failed or log its contents.
                audit(conn, identity, job["patient_id"], "vitals_refresh", uuid4(), result="error")
                return True
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
    run_worker(cfg, identity, once=args.once)


def run_worker(cfg: Settings, identity: Identity, *, once=False):
    """Shared ingestion, safety scheduling and retention loop for CLI and hosted entrypoints."""
    logger = logging.getLogger("patient_memory.worker")
    sender = sender_from_settings(cfg)
    retired_at = scheduled_at = None
    while True:
        if retired_at is None or time.monotonic() - retired_at >= RETIRE_EVERY_S:
            try:  # KAZE 24 h retention; a no-op outside safety tenants
                retire_sessions(cfg, identity)
            except psycopg.Error:
                logger.exception("session retention failed")
            retired_at = time.monotonic()
        if scheduled_at is None or time.monotonic() - scheduled_at >= PASS_EVERY_S:
            try:  # KAZE ladder (BL-26); finds nothing outside a safety tenant
                run_pass(cfg, identity, sender)
            except psycopg.Error:
                logger.exception("KAZE scheduler pass failed")
            scheduled_at = time.monotonic()
        worked = run_once(cfg, identity)
        if once:
            return
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
