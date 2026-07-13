"""Deterministic offline metrics for the 23-occupation product surface."""

from __future__ import annotations

from typing import Any

from app.services.occupation_taxonomy import (
    classify_title,
    occupation_by_key,
    occupation_keys,
)
from app.services.people.context import _build_roles_context
from app.services.people.ranking import _peer_title_alignment_rank
from app.services.people.titles import _companywide_manager_titles
from app.services.resume_artifact.latex import _supported_terms
from app.services.resume_artifact.quality import _job_terms, _term_present


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_cross_category_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate job, people, and resume invariants for a frozen case corpus."""
    expected_taxonomy = set(occupation_keys())
    case_keys = {str(case.get("key") or "") for case in cases}

    job_true_positive = 0
    job_predictions = 0
    job_critical_hits = 0
    job_critical_total = 0
    people_context_hits = 0
    people_peer_hits = 0
    people_manager_hits = 0
    resume_supported_hits = 0
    resume_supported_total = 0
    resume_unsupported_blocked = 0
    resume_unsupported_total = 0
    category_results: list[dict[str, Any]] = []

    for case in cases:
        key = str(case["key"])
        occupation = occupation_by_key(key)
        job = case["job"]
        people = case["people"]
        resume = case["resume"]

        predictions = classify_title(job["title"], job.get("description"))
        job_true_positive += int(key in predictions)
        job_predictions += len(predictions)

        job_obj = type("EvalJob", (), {
            "title": job["title"],
            "description": job.get("description") or "",
            "tags": [f"occupation:{key}"],
        })()
        extracted_terms = _job_terms(job_obj)
        critical_hits = sum(
            1 for term in job.get("critical_terms") or []
            if any(
                _term_present(str(extracted), str(term))
                or _term_present(str(term), str(extracted))
                for extracted in extracted_terms
            )
        )
        job_critical_hits += critical_hits
        job_critical_total += len(job.get("critical_terms") or [])

        context = _build_roles_context([job["title"]])
        context_ok = bool(
            context
            and occupation
            and key in context.occupation_keys
            and context.department == occupation.department_bucket
        )
        people_context_hits += int(context_ok)
        peer_ok = bool(
            context
            and _peer_title_alignment_rank(
                {"title": people["peer"]}, context=context
            ) < _peer_title_alignment_rank(
                {"title": people["wrong_function"]}, context=context
            )
        )
        people_peer_hits += int(peer_ok)
        managers = _companywide_manager_titles(context)
        manager_ok = people["manager"].casefold() in {
            title.casefold() for title in managers
        }
        people_manager_hits += int(manager_ok)

        supported = list(resume.get("supported") or [])
        unsupported = list(resume.get("unsupported") or [])
        parsed = {
            "skills": supported,
            "experience": [{
                "title": job["title"],
                "company": "Example Employer",
                "bullets": [
                    "Demonstrated " + ", ".join(supported) + " through measurable work."
                ],
            }],
        }
        supported_renderable = set(_supported_terms(supported, parsed))
        unsupported_renderable = set(_supported_terms(unsupported, parsed))
        supported_hits = sum(term in supported_renderable for term in supported)
        unsupported_blocked = sum(
            term not in unsupported_renderable for term in unsupported
        )
        resume_supported_hits += supported_hits
        resume_supported_total += len(supported)
        resume_unsupported_blocked += unsupported_blocked
        resume_unsupported_total += len(unsupported)

        category_results.append({
            "key": key,
            "job_classification": key in predictions,
            "job_predictions": predictions,
            "critical_term_recall": _ratio(
                critical_hits, len(job.get("critical_terms") or [])
            ),
            "people_context": context_ok,
            "peer_preference": peer_ok,
            "manager_seed": manager_ok,
            "resume_supported_gate": supported_hits == len(supported),
            "resume_unsupported_gate": unsupported_blocked == len(unsupported),
        })

    count = len(cases)
    return {
        "schema_version": 1,
        "category_count": count,
        "taxonomy_coverage": _ratio(
            len(case_keys & expected_taxonomy), len(expected_taxonomy)
        ),
        "missing_categories": sorted(expected_taxonomy - case_keys),
        "unknown_categories": sorted(case_keys - expected_taxonomy),
        "jobs": {
            "occupation_recall": _ratio(job_true_positive, count),
            "occupation_precision": _ratio(job_true_positive, job_predictions),
            "critical_term_recall": _ratio(job_critical_hits, job_critical_total),
        },
        "people": {
            "context_accuracy": _ratio(people_context_hits, count),
            "peer_preference_accuracy": _ratio(people_peer_hits, count),
            "manager_seed_coverage": _ratio(people_manager_hits, count),
        },
        "resumes": {
            "supported_term_retention": _ratio(
                resume_supported_hits, resume_supported_total
            ),
            "unsupported_term_block_rate": _ratio(
                resume_unsupported_blocked, resume_unsupported_total
            ),
        },
        "categories": category_results,
    }
