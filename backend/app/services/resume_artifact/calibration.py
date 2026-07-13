"""Outcome calibration report for the internal resume-readiness score.

The score remains explicitly internal until each occupation/experience cohort
has enough real observations and higher score bands are monotonic for review,
application, and interview outcomes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.resume_artifact import ResumeArtifact


CALIBRATION_SCHEMA_VERSION = 1
SCORE_BANDS = ((0, 59), (60, 69), (70, 79), (80, 89), (90, 100))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _monotonic(values: list[float | None]) -> bool:
    observed = [value for value in values if value is not None]
    return len(observed) >= 2 and all(
        current <= following
        for current, following in zip(observed, observed[1:])
    )


def compute_readiness_calibration(
    samples: list[dict[str, Any]],
    *,
    minimum_cohort_size: int = 30,
) -> dict[str, Any]:
    cohorts: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        score = sample.get("score")
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            continue
        cohort = (
            str(sample.get("occupation") or "unknown"),
            str(sample.get("experience_level") or "unknown"),
        )
        cohorts[cohort].append({**sample, "score": float(score)})

    reports: list[dict[str, Any]] = []
    for (occupation, experience_level), cohort_samples in sorted(cohorts.items()):
        bands: list[dict[str, Any]] = []
        for minimum, maximum in SCORE_BANDS:
            rows = [
                sample for sample in cohort_samples
                if minimum <= sample["score"] <= maximum
            ]
            bands.append({
                "label": f"{minimum}-{maximum}",
                "count": len(rows),
                "review_acceptance_rate": _rate(
                    sum(bool(row.get("review_accepted")) for row in rows), len(rows)
                ),
                "application_rate": _rate(
                    sum(bool(row.get("applied")) for row in rows), len(rows)
                ),
                "interview_rate": _rate(
                    sum(bool(row.get("interviewed")) for row in rows), len(rows)
                ),
            })
        sufficient = len(cohort_samples) >= minimum_cohort_size
        monotonic = {
            metric: _monotonic([band[metric] for band in bands])
            for metric in (
                "review_acceptance_rate",
                "application_rate",
                "interview_rate",
            )
        }
        reports.append({
            "occupation": occupation,
            "experience_level": experience_level,
            "sample_count": len(cohort_samples),
            "sufficient_sample": sufficient,
            "bands": bands,
            "monotonic": monotonic,
            "calibrated": sufficient and all(monotonic.values()),
        })

    return {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "minimum_cohort_size": minimum_cohort_size,
        "sample_count": sum(len(rows) for rows in cohorts.values()),
        "cohorts": reports,
        "calibrated": bool(reports) and all(report["calibrated"] for report in reports),
    }


async def load_readiness_calibration(
    db: AsyncSession,
    *,
    minimum_cohort_size: int = 30,
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(ResumeArtifact, Job).join(Job, Job.id == ResumeArtifact.job_id)
        )
    ).all()
    samples: list[dict[str, Any]] = []
    for artifact, job in rows:
        decisions = artifact.rewrite_decisions or {}
        decided = [value for value in decisions.values() if value in {"accepted", "rejected"}]
        accepted = sum(value == "accepted" for value in decided)
        occupation_keys = [
            tag.split(":", 1)[1]
            for tag in (job.tags or [])
            if isinstance(tag, str) and tag.startswith("occupation:")
        ] or ["unknown"]
        for occupation in occupation_keys:
            samples.append({
                "score": artifact.quality_score,
                "occupation": occupation,
                "experience_level": job.experience_level or "unknown",
                "review_accepted": bool(decided) and accepted / len(decided) >= 0.5,
                "applied": job.stage in {
                    "applied", "interviewing", "offer", "accepted", "rejected", "withdrawn"
                },
                "interviewed": job.stage in {"interviewing", "offer", "accepted"},
            })
    return compute_readiness_calibration(
        samples,
        minimum_cohort_size=minimum_cohort_size,
    )
