"""Fail-closed policy for user-visible aggregate scores.

NexusReach persists deterministic scores for ordering, reuse gates, and offline
evaluation. Those numbers are not hiring-outcome probabilities. Aggregate
0-100 values must remain hidden from public responses until a reviewed,
versioned calibration release has demonstrated monotonic user outcomes for the
relevant cohort. Evidence dimensions remain public because they describe
directly observable coverage rather than predicted outcomes.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCORE_DISPLAY_POLICY_VERSION = 1


def uncalibrated_score_status(score_kind: str) -> dict[str, Any]:
    return {
        "schema_version": SCORE_DISPLAY_POLICY_VERSION,
        "score_kind": score_kind,
        "calibrated": False,
        "display_mode": "dimensions_only",
        "reason": (
            "Aggregate score withheld until a versioned outcome-calibration "
            "release passes cohort sufficiency and monotonicity gates."
        ),
    }


def public_match_score(_internal_score: Any) -> tuple[None, dict[str, Any]]:
    """Never expose the current internal job-ordering aggregate."""
    return None, uncalibrated_score_status("job_match")


def public_resume_quality_evaluation(
    evaluation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return dimension evidence while withholding uncalibrated aggregates."""
    if not isinstance(evaluation, dict):
        return None
    public = deepcopy(evaluation)
    public["calibration"] = uncalibrated_score_status("resume_readiness")
    public["overall_score"] = None
    public["readiness"] = None
    return public
