from datetime import datetime, timedelta

import jwt

from patient_memory.domain import now
from patient_memory.errors import Problem
from patient_memory.retrieval import evidence, scoped_facts
from patient_memory.storage import audit


def paginate(conn, cfg, actor, patient, as_of, known_at, start, end, limit, cursor, request_id):
    offset = 0
    if cursor:
        try:
            data = jwt.decode(cursor, cfg.jwt_secret, algorithms=["HS256"],
                              audience="patient-memory-cursor", options={"require": ["exp", "sub"]})
            if (data["sub"] != str(actor.principal_id) or data["tenant"] != str(actor.tenant_id)
                    or data["patient"] != str(patient["id"]) or data["revision"] != patient["revision"]):
                raise ValueError("scope")
            for key, supplied in [("asof", as_of), ("known", known_at), ("start", start), ("end", end)]:
                stored = datetime.fromisoformat(data[key]) if data[key] else None
                if supplied is not None and supplied != stored:
                    raise ValueError("changed_cutoff")
            as_of = datetime.fromisoformat(data["asof"])
            known_at = datetime.fromisoformat(data["known"])
            start = datetime.fromisoformat(data["start"]) if data["start"] else None
            end = datetime.fromisoformat(data["end"]) if data["end"] else None
            offset = data["offset"]
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise Problem(409, "cursor_expired") from exc
    as_of, known_at = as_of or now(), known_at or now()
    facts = scoped_facts(conn, patient["id"], as_of, known_at)
    facts = [f for f in facts if (not start or f["valid_from"] and f["valid_from"] >= start)
             and (not end or f["valid_from"] and f["valid_from"] <= end)]
    page = facts[offset:offset + limit]
    next_cursor = None
    if offset + limit < len(facts):
        data = {"sub": str(actor.principal_id), "tenant": str(actor.tenant_id),
                "patient": str(patient["id"]), "revision": patient["revision"],
                "asof": as_of.isoformat(), "known": known_at.isoformat(),
                "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                "offset": offset + limit, "aud": "patient-memory-cursor", "exp": now() + timedelta(minutes=15)}
        next_cursor = jwt.encode(data, cfg.jwt_secret, algorithm="HS256")
    pending = conn.execute("SELECT count(*) AS n FROM sources WHERE patient_id=%s AND ingested_at<=%s "
                           "AND published_at IS NULL AND retracted_at IS NULL AND purged_at IS NULL",
                           (patient["id"], known_at)).fetchone()["n"]
    audit(conn, actor, patient["id"], "timeline", request_id)
    return {"events": [{**evidence(f).model_dump(mode="json"),
                        "effective_from": f["valid_from"], "effective_to": f["valid_to"],
                        "concept": f["concept"], "polarity": f["polarity"],
                        "event_type": f["event_type"], "order_id": f["order_id"]} for f in page],
            "next_cursor": next_cursor, "memory_revision": patient["revision"],
            "coverage": {"index_complete": not pending, "truncated": False, "degraded_mode": None}}
