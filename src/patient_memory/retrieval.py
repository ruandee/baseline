from datetime import datetime

from patient_memory.domain import Evidence
from patient_memory.extraction import embed, terms, vector_sql
from patient_memory.storage import patient_access

# All ranks operate on a materialized patient/time/visibility scoped relation.
SCOPED = """
WITH scoped AS MATERIALIZED (
 SELECT f.*, s.payload, s.canonical_text,s.recorded_at,s.ingested_at,s.published_at
 FROM facts f JOIN sources s ON s.tenant_id=f.tenant_id AND s.patient_id=f.patient_id AND s.id=f.source_id
 WHERE f.patient_id=%(patient)s AND s.published_at<=%(known)s AND s.ingested_at<=%(known)s
 AND (s.retracted_at IS NULL OR s.retracted_at>%(known)s) AND s.purged_at IS NULL
 AND (f.valid_from IS NULL OR f.valid_from<=%(asof)s)
 AND NOT EXISTS(SELECT FROM sources amended WHERE amended.tenant_id=s.tenant_id
  AND amended.patient_id=s.patient_id AND amended.supersedes=s.id
  AND amended.published_at<=%(known)s AND amended.ingested_at<=%(known)s
  AND (amended.retracted_at IS NULL OR amended.retracted_at>%(known)s))
)
"""


def scoped_facts(conn, patient_id, as_of, known_at):
    patient_access(conn, patient_id)
    return conn.execute(SCOPED + "SELECT * FROM scoped ORDER BY valid_from NULLS LAST,source_id,id",
                        {"patient": patient_id, "asof": as_of, "known": known_at}).fetchall()


def retrieve(conn, patient_id, as_of, known_at, question, limit=12, summary=False):
    patient_access(conn, patient_id)
    params = {"patient": patient_id, "asof": as_of, "known": known_at,
              "q": question, "vector": vector_sql(embed(question))}
    if summary:
        candidates = scoped_facts(conn, patient_id, as_of, known_at)
        candidates.sort(key=lambda x: (x["valid_from"] or datetime.min.replace(tzinfo=as_of.tzinfo), str(x["id"])), reverse=True)
    else:
        candidates = conn.execute(SCOPED + """
        , lexical AS (
          SELECT id,row_number() OVER(ORDER BY ts_rank(search,websearch_to_tsquery('english',%(q)s)) DESC,id) AS rank
          FROM scoped WHERE search @@ websearch_to_tsquery('english',%(q)s) LIMIT 30
        ), vectors AS (
          SELECT id,row_number() OVER(ORDER BY embedding <=> %(vector)s::vector,id) AS rank
          FROM scoped ORDER BY embedding <=> %(vector)s::vector,id LIMIT 30
        )
        SELECT s.*,(coalesce(1.0/(60+l.rank),0)+coalesce(1.0/(60+v.rank),0)) AS score
        FROM scoped s LEFT JOIN lexical l USING(id) LEFT JOIN vectors v USING(id)
        WHERE l.id IS NOT NULL OR v.id IS NOT NULL ORDER BY score DESC,s.id
        """, params).fetchall()
        # Hash embeddings alone cannot establish relevance; require a lexical term match.
        candidates = [f for f in candidates if terms(question) & terms(f["concept"] + " " + f["quote"])]
        concepts = {f["concept"] for f in candidates if f["concept"] != "source_assertion"}
        if concepts:
            found = {f["id"] for f in candidates}
            candidates += [f for f in scoped_facts(conn, patient_id, as_of, known_at)
                           if f["concept"] in concepts and f["id"] not in found]
    # Count visible eligible but unpublished sources; failures are incomplete, not absent.
    pending = conn.execute(
        "SELECT count(*) AS n FROM sources WHERE patient_id=%s AND ingested_at<=%s "
        "AND published_at IS NULL AND retracted_at IS NULL AND purged_at IS NULL",
        (patient_id, known_at),
    ).fetchone()["n"]
    picked, budget = [], 0
    for candidate in candidates:
        size = len(candidate["quote"].encode("utf-8"))
        if len(picked) >= limit or budget + size > 6000:
            break
        picked.append(candidate)
        budget += size
    return picked, {"index_complete": pending == 0, "truncated": len(picked) < len(candidates),
                    "degraded_mode": "hash_embedding_baseline"}


def evidence(fact):
    return Evidence(
        evidence_id=fact["id"], source_version_id=fact["source_id"],
        source_kind=fact["payload"]["kind"], author_role=fact["payload"]["author_role"],
        recorded_at=fact["recorded_at"], ingested_at=fact["ingested_at"],
        quote=fact["quote"], start=fact["start_offset"], end=fact["end_offset"],
    )
