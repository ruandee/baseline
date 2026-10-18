"""Documented measurements for nurse readback, never inferred normal/negative findings."""
import math

from patient_memory.domain import DocumentedObservation


def documented_observations(conn, patient_id, at, days):
    """Latest temperature fact under the caller's RLS and current source lifecycle.

    Preserve its recorded time and exact evidence. This is a measurement, not a fever or
    normal-range classification; no data, unsupported units or nonnumeric values stay unknown.
    """
    row = conn.execute(
        "SELECT f.id,f.source_id,f.value,f.unit,f.quote,s.recorded_at,"
        " COALESCE(f.valid_from,s.recorded_at) AS effective_at"
        " FROM facts f JOIN sources s ON s.tenant_id=f.tenant_id AND s.patient_id=f.patient_id"
        " AND s.id=f.source_id WHERE f.patient_id=%s AND f.concept='temperature_c'"
        " AND f.polarity='present' AND f.experiencer='patient' AND s.payload->>'kind'='observation'"
        " AND s.published_at IS NOT NULL AND s.retracted_at IS NULL AND s.purged_at IS NULL"
        " AND COALESCE(f.valid_from,s.recorded_at)<=%s AND s.recorded_at<=%s"
        " AND (f.valid_to IS NULL OR f.valid_to>%s)"
        " AND s.recorded_at>=%s - make_interval(days=>%s)"
        " AND NOT EXISTS(SELECT FROM sources newer WHERE newer.tenant_id=s.tenant_id"
        " AND newer.patient_id=s.patient_id AND newer.supersedes=s.id"
        " AND newer.published_at IS NOT NULL AND newer.retracted_at IS NULL AND newer.purged_at IS NULL)"
        " ORDER BY effective_at DESC,s.recorded_at DESC,s.ingested_at DESC,f.id DESC LIMIT 1",
        (patient_id, at, at, at, at, days)).fetchone()
    if not row or row["unit"] not in ("C", "\u00b0C", "Cel"):
        return []
    try:
        value = float(row["value"])
    except (ValueError, TypeError):
        return []
    if not math.isfinite(value):
        return []
    return [DocumentedObservation(
        evidence_id=row["id"], source_id=row["source_id"], concept="temperature_c", value=value,
        unit="C", label=f"Temperature {value:g} \u00b0C documented", quote=row["quote"],
        recorded_at=row["recorded_at"], effective_at=row["effective_at"], source_kind="observation"
    ).model_dump(mode="json")]
