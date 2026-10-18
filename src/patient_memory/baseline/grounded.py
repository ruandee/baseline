"""Deterministic multimodal draft assembly; no provider or clinical policy (ADR029)."""
from math import isfinite

from patient_memory.baseline.engine import REGISTRY
from patient_memory.baseline.verdict import ACTION_LABELS

SPEECH_META = {
    "speech_rate_wpm": ("Speech rate", "words/min"),
    "pause_ratio": ("Pause ratio", "share of time"),
    "mean_pause_s": ("Mean pause", "s"),
    "f0_median_hz": ("Pitch (F0)", "Hz"),
}


def multimodal_template(name, decision, modalities, tags, corroborated=False):
    """Only registered, current flags with exact comparison provenance can produce prose.

    Measurements are reported without interpreting their cause. Each comparison cites the
    immutable current capture and every capture/fact used in its computed baseline.
    Missing provenance withholds the entire draft, never substitutes speech-only wording.
    """
    if decision.verdict not in ("watch", "escalate"):
        return None
    sentences, supporting = [], []
    for modality, entry in sorted(modalities.items()):
        if not entry.get("current") or entry.get("status") not in ("provisional", "change"):
            continue
        spec = REGISTRY.get(modality)
        baseline = entry.get("params", {}).get("baseline_evidence_ids", [])
        citations = list(dict.fromkeys([*entry.get("evidence_ids", []), *baseline]))
        if spec is None or not entry.get("evidence_ids") or not baseline or len(citations) > 64:
            return None
        comparisons = []
        for feature in spec.features:
            values = entry.get("per_feature", {}).get(feature.name)
            if not values:
                continue
            value, median = values.get("value"), values.get("median")
            if not all(isinstance(v, (int, float)) and isfinite(v) for v in (value, median)):
                return None
            label, unit = SPEECH_META.get(feature.name, (feature.label, feature.unit))
            if not label or not unit:
                return None
            comparisons.append(f"{label} {value:.2f} vs baseline median {median:.2f} {unit}")
        if not comparisons or not entry.get("ts"):
            return None
        sentences.append({"section": "S", "text": f"{name}: {modality} measurements at {entry['ts']}: "
                          + "; ".join(comparisons) + ".", "evidence_ids": citations})
        supporting.extend(entry.get("evidence_ids", []))
    if not sentences:
        return None
    tags = [tag for tag in tags if tag.get("evidence_id")]
    sentences.append({"section": "B", "text": "; ".join(t["label"] for t in tags) + "." if tags
                      else "No context supplied for this assessment.",
                      "evidence_ids": list(dict.fromkeys(t["evidence_id"] for t in tags))})
    states = "; ".join(f"{m}: {e['status']}" for m, e in sorted(modalities.items())
                       if e.get("current") and e.get("status") in ("provisional", "change"))
    citations = list(dict.fromkeys(supporting))
    sentences.extend([
        {"section": "A", "text": "Engineering signal status (not clinically validated): " + states
         + (". Changes in multiple modalities corroborate the assessment." if corroborated else "."),
         "evidence_ids": citations},
        {"section": "R", "text": f"Suggest {ACTION_LABELS[decision.action]}.", "evidence_ids": citations},
    ])
    if len(sentences) > 12 or any(len(s["evidence_ids"]) > 64 or len(s["text"]) > 1500 for s in sentences):
        return None
    return {"source": "template", "sentences": sentences}
