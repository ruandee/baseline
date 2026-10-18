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
