"""Privacy-safe cross-surface attribution for ranking and outcome events."""

from __future__ import annotations

import hashlib
from typing import Any


def attribution_key(value: Any | None) -> str | None:
    """Stable pseudonymous join key; never emit raw database identifiers."""
    if value is None:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def _string(value: Any, default: str = "unknown") -> str:
    return value if isinstance(value, str) and value else default


def person_ranking_properties(person: Any | None) -> dict[str, Any]:
    if person is None:
        return {}
    corroborated = getattr(person, "corroborated_by", None)
    profile_data = getattr(person, "profile_data", None)
    if not isinstance(profile_data, dict):
        profile_data = {}
    return {
        "person_source": _string(getattr(person, "source", None)),
        "person_type": _string(getattr(person, "person_type", None)),
        "match_quality": _string(
            profile_data.get("match_quality") or getattr(person, "match_quality", None)
        ),
        "company_match_confidence": _string(
            profile_data.get("company_match_confidence")
            or getattr(person, "company_match_confidence", None)
        ),
        "has_warm_path": bool(profile_data.get("warm_path_type")),
        "corroborated": len(corroborated or profile_data.get("corroborated_by") or []) >= 2,
    }


def job_category_properties(job: Any | None) -> dict[str, Any]:
    if job is None:
        return {}
    occupation_keys = sorted({
        tag.split(":", 1)[1]
        for tag in (getattr(job, "tags", None) or [])
        if isinstance(tag, str) and tag.startswith("occupation:")
    })
    return {
        "occupation_keys": occupation_keys,
        "experience_level": _string(getattr(job, "experience_level", None)),
    }


def artifact_quality_properties(artifact: Any | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    score = getattr(artifact, "quality_score", None)
    evaluation = getattr(artifact, "quality_evaluation", None)
    profile = evaluation.get("profile") if isinstance(evaluation, dict) else None
    return {
        "internal_quality_score": float(score) if isinstance(score, (int, float)) else None,
        "quality_profile": profile if isinstance(profile, str) else "unknown",
        "job_key": attribution_key(getattr(artifact, "job_id", None)),
        "artifact_key": attribution_key(getattr(artifact, "id", None)),
    }
