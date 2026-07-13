from app.services.resume_artifact.calibration import compute_readiness_calibration


def _samples(*, reversed_outcomes: bool = False) -> list[dict]:
    samples = []
    for score, positive in ((55, False), (65, False), (75, True), (85, True), (95, True)):
        outcome = not positive if reversed_outcomes else positive
        for _ in range(6):
            samples.append({
                "score": score,
                "occupation": "healthcare",
                "experience_level": "mid",
                "review_accepted": outcome,
                "applied": outcome,
                "interviewed": outcome,
            })
    return samples


def test_calibration_requires_sample_size_and_monotonic_outcomes():
    report = compute_readiness_calibration(_samples(), minimum_cohort_size=30)
    cohort = report["cohorts"][0]

    assert cohort["sufficient_sample"] is True
    assert cohort["monotonic"] == {
        "review_acceptance_rate": True,
        "application_rate": True,
        "interview_rate": True,
    }
    assert cohort["calibrated"] is True
    assert report["calibrated"] is True


def test_calibration_fails_closed_for_small_or_nonmonotonic_cohorts():
    small = compute_readiness_calibration(_samples()[:10], minimum_cohort_size=30)
    reversed_report = compute_readiness_calibration(
        _samples(reversed_outcomes=True), minimum_cohort_size=30
    )

    assert small["cohorts"][0]["sufficient_sample"] is False
    assert small["calibrated"] is False
    assert reversed_report["cohorts"][0]["calibrated"] is False
    assert reversed_report["calibrated"] is False
