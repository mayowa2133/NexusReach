"""Outcome calibration report for the internal resume-readiness score.

The score remains explicitly internal until each occupation/experience cohort
has enough real observations and higher score bands are monotonic for review,
application, and interview outcomes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.resume_artifact import ResumeArtifact


CALIBRATION_SCHEMA_VERSION = 1
SCORE_BANDS = ((0, 59), (60, 69), (70, 79), (80, 89), (90, 100))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _monotonic(values: list[float | None], *, minimum_observed_bands: int) -> bool:
    observed = [value for value in values if value is not None]
    return len(observed) >= minimum_observed_bands and all(
        current <= following
        for current, following in zip(observed, observed[1:])
    )


def _observed_rate(rows: list[dict[str, Any]], key: str) -> tuple[int, float | None]:
    observed = [row[key] for row in rows if isinstance(row.get(key), bool)]
    return len(observed), _rate(sum(observed), len(observed))


def compute_readiness_calibration(
    samples: list[dict[str, Any]],
    *,
    minimum_cohort_size: int = 30,
    minimum_band_size: int = 5,
    minimum_observed_bands: int = 3,
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
            band: dict[str, Any] = {
                "label": f"{minimum}-{maximum}",
                "count": len(rows),
            }
            for sample_key, metric in (
                ("review_accepted", "review_acceptance_rate"),
                ("applied", "application_rate"),
                ("interviewed", "interview_rate"),
            ):
                observations, rate = _observed_rate(rows, sample_key)
                band[f"{metric}_observations"] = observations
                band[metric] = rate if observations >= minimum_band_size else None
            bands.append(band)
        sufficient = len(cohort_samples) >= minimum_cohort_size
        monotonic = {
            metric: _monotonic(
                [band[metric] for band in bands],
                minimum_observed_bands=minimum_observed_bands,
            )
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
        "minimum_band_size": minimum_band_size,
        "minimum_observed_bands": minimum_observed_bands,
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
    now = datetime.now(timezone.utc)
    for artifact, job in rows:
        decisions = artifact.rewrite_decisions or {}
        decided = [value for value in decisions.values() if value in {"accepted", "rejected"}]
        accepted = sum(value == "accepted" for value in decided)
        generated_at = artifact.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        age = now - generated_at
        applied = job.stage in {
            "applied", "interviewing", "offer", "accepted", "rejected", "withdrawn"
        }
        interviewed = job.stage in {"interviewing", "offer", "accepted"}
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
                "review_accepted": (
                    accepted / len(decided) >= 0.5 if decided else None
                ),
                # Do not turn still-maturing artifacts into false negatives.
                "applied": applied if applied or age >= timedelta(days=30) else None,
                "interviewed": (
                    interviewed if interviewed or age >= timedelta(days=60) else None
                ),
            })
    return compute_readiness_calibration(
        samples,
        minimum_cohort_size=minimum_cohort_size,
    )
