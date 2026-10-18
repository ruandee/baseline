"""Storage/response compatibility for modality-keyed assessments (decision 025).

Historical rows retain their flat speech feature maps; new rows store a map per modality.
These helpers never reinterpret an absent modality as a negative finding.
"""


def features_for(features: dict, modality: str = "speech") -> dict:
    if isinstance(features.get(modality), dict):
        return features[modality]
    # Legacy flat speech rows have scoring-stat dictionaries, not modality dictionaries.
    if modality == "speech" and all(isinstance(v, dict) and "value" in v
                                    for v in features.values()):
        return features
    return {}


def stored_modalities(row: dict) -> dict:
    """Per-modality API projection, including explicitly stale and unavailable evidence."""
    params = row["params"]
    results = params.get("modality_results")
    if results is not None:
        return {name: {**metadata, "per_feature": features_for(row["features"], name)}
                for name, metadata in results.items()}
    return {"speech": {"status": row["change_status"], "ts": row["check_ts"].isoformat(),
                       "check_id": str(row["check_id"]), "current": True,
                       "fused_z": row["fused_z"], "params": params,
                       "evidence_ids": ["check:" + str(row["check_id"])],
                       "per_feature": features_for(row["features"])}}


def signal_sources(conn, patient_id, check):
    """Authorize immutable fact citations for an internal non-speech adapter.

    Adapters own capture and feature extraction; this is not a public signal-ingestion API.
    A missing/foreign/inactive/future citation cannot corroborate a clinical assessment.
    """
    from uuid import UUID

    from patient_memory.errors import Problem

    if not check.evidence_ids:
        raise Problem(422, "signal_evidence_required")
    try:
        ids = {UUID(value) for value in check.evidence_ids}
    except (ValueError, TypeError, AttributeError) as exc:
        raise Problem(422, "signal_evidence_required") from exc
    rows = conn.execute(
        "SELECT f.id,f.source_id FROM facts f JOIN sources s ON s.tenant_id=f.tenant_id "
        "AND s.patient_id=f.patient_id AND s.id=f.source_id WHERE f.patient_id=%s AND f.id=ANY(%s) "
        "AND s.published_at IS NOT NULL AND s.retracted_at IS NULL AND s.purged_at IS NULL "
        "AND COALESCE(f.valid_from,s.recorded_at)<=%s AND s.recorded_at<=%s "
        "AND (f.valid_to IS NULL OR f.valid_to>%s) "
        "AND NOT EXISTS(SELECT FROM sources newer WHERE newer.tenant_id=s.tenant_id "
        "AND newer.patient_id=s.patient_id AND newer.supersedes=s.id "
        "AND newer.published_at IS NOT NULL AND newer.retracted_at IS NULL "
        "AND newer.purged_at IS NULL)", (patient_id, list(ids), check.ts, check.ts, check.ts)).fetchall()
    if {row["id"] for row in rows} != ids:
        raise Problem(409, "signal_evidence_unavailable")
    return {str(row["source_id"]) for row in rows}
