"""Bucket assembly, match metadata application, and finalization for people discovery."""

import copy
import logging
import uuid


from app.models.person import Person
from app.utils.job_context import (
    JobContext,
)
from app.utils.linkedin import normalize_linkedin_url

from app.services.people.candidates import _candidate_key
from app.services.people.classify import _classify_org_level, _classify_person, _compute_match_metadata
from app.services.people.company_match import _classify_employment_status
from app.services.people.identity import _normalize_identity
from app.services.people.ranking import _bucket_role_fit_rank, _company_match_confidence, _compute_usefulness_score, _confidence_rank, _linkedin_signal_rank, _manager_person_title_specificity_rank, _match_rank, _org_rank, _peer_person_title_alignment_rank, _person_location_match_rank, _recruiter_person_scope_rank, _warm_path_rank
from app.services.people.titles import _is_senior_ic_fallback
logger = logging.getLogger(__name__)


def _apply_match_metadata(
    person: Person,
    data: dict,
    person_type: str,
    context: JobContext | None,
    company_name: str | None = None,
    public_identity_slugs: list[str] | None = None,
) -> None:
    match_quality, match_reason = _compute_match_metadata(data, person_type, context)
    employment_status = data.get("_employment_status")
    if not employment_status and company_name:
        employment_status = _classify_employment_status(data, company_name)
    org_level = data.get("_org_level") or _classify_org_level(
        person.title or data.get("title", ""),
        source=data.get("source", ""),
        snippet=data.get("snippet", ""),
    )

    if data.get("_director_fallback"):
        match_quality = "next_best"
        match_reason = "Senior leader fallback at the target company."

    bucket_name = {
        "recruiter": "recruiters",
        "hiring_manager": "hiring_managers",
        "peer": "peers",
    }.get(person_type, "peers")
    usefulness = _compute_usefulness_score(
        data,
        bucket=bucket_name,
        context=context,
        company_name=company_name or "",
        public_identity_slugs=public_identity_slugs,
    )

    setattr(person, "match_quality", match_quality)
    setattr(person, "match_reason", match_reason)
    setattr(person, "company_match_confidence", None)
    setattr(person, "fallback_reason", match_reason if match_quality == "next_best" else None)
    setattr(person, "employment_status", employment_status)
    setattr(person, "org_level", org_level)
    setattr(person, "usefulness_score", usefulness)


def _append_bucket(
    bucketed: dict[str, list[Person]],
    seen: dict[str, set[str]],
    person: Person,
    data: dict,
    explicit_type: str | None = None,
    context: JobContext | None = None,
    company_name: str | None = None,
    public_identity_slugs: list[str] | None = None,
) -> None:
    person_type = explicit_type or _classify_person(
        person.title or data.get("title", ""),
        source=data.get("source", ""),
        snippet=data.get("snippet", ""),
    )
    person.person_type = person_type
    _apply_match_metadata(
        person, data, person_type, context,
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
    )

    bucket_name = {
        "recruiter": "recruiters",
        "hiring_manager": "hiring_managers",
        "peer": "peers",
    }[person_type]
    profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
    identity_key = (
        str(person.id)
        if person.id
        else normalize_linkedin_url(person.linkedin_url or "")
        or str(profile_data.get("public_url") or "")
        or _candidate_key(data)
    )
    if identity_key in seen[bucket_name]:
        return
    seen[bucket_name].add(identity_key)
    bucketed[bucket_name].append(person)


def _bucketed_linkedin_slugs(bucketed: dict[str, list[Person]]) -> list[str]:
    slugs: set[str] = set()
    for people in bucketed.values():
        for person in people:
            normalized = normalize_linkedin_url(person.linkedin_url)
            if normalized:
                slugs.add(normalized.rstrip("/").rsplit("/", 1)[-1])
    return sorted(slugs)


def _dedupe_bucket_assignments(bucketed: dict[str, list[Person]]) -> dict[str, list[Person]]:
    winners: dict[uuid.UUID, tuple[str, tuple[int, int, int, int, int, int, str]]] = {}
    for bucket, people in bucketed.items():
        for person in people:
            if not person.id or getattr(person, "_synthetic_fallback", False):
                # Synthetic cross-bucket clones (e.g. the senior-IC hiring-manager
                # fallback) don't contest id ownership — they coexist with the
                # original (audit pass-2 P8).
                continue
            usefulness = getattr(person, "usefulness_score", None) or 0
            rank = (
                _match_rank(getattr(person, "match_quality", None)),
                100 - usefulness,
                _bucket_role_fit_rank(bucket, person),
                0 if getattr(person, "company_match_confidence", None) == "verified" else 1,
                _warm_path_rank(person),
                _linkedin_signal_rank(person),
                0 if person.linkedin_url else 1,
                _normalize_identity(person.full_name),
            )
            current = winners.get(person.id)
            if current is None or rank < current[1]:
                winners[person.id] = (bucket, rank)

    deduped: dict[str, list[Person]] = {}
    for bucket, people in bucketed.items():
        deduped[bucket] = [
            person
            for person in people
            if not person.id
            or getattr(person, "_synthetic_fallback", False)
            or winners.get(person.id, (None, None))[0] == bucket
        ]
    return deduped


def _finalize_bucketed(
    bucketed: dict[str, list[Person]],
    *,
    target_count_per_bucket: int,
    location_terms: list[str] | None = None,
    context: JobContext | None = None,
) -> dict[str, list[Person]]:
    finalized: dict[str, list[Person]] = {}
    for bucket, people in bucketed.items():
        ordered: list[Person] = []
        for person in people:
            company_match_confidence = _company_match_confidence(person)
            setattr(person, "company_match_confidence", company_match_confidence)

            if company_match_confidence != "verified":
                setattr(person, "match_quality", "next_best")
                if not getattr(person, "fallback_reason", None):
                    fallback_reason = (
                        "Strong same-company signal, but current employment is not fully verified."
                        if company_match_confidence == "strong_signal"
                        else "Lower-confidence same-company fallback."
                    )
                    setattr(person, "fallback_reason", fallback_reason)
            else:
                setattr(person, "fallback_reason", None)

            ordered.append(person)

        ordered.sort(
            key=lambda person: (
                0
                if getattr(person, "company_match_confidence", None) in {"verified", "strong_signal"}
                else 1,
                _manager_person_title_specificity_rank(person) if bucket == "hiring_managers" else 0,
                _recruiter_person_scope_rank(person) if bucket == "recruiters" else 1,
                _person_location_match_rank(person, location_terms) if bucket in {"recruiters", "peers"} else 1,
                _peer_person_title_alignment_rank(person, context) if bucket == "peers" else 1,
                _warm_path_rank(person),
                _linkedin_signal_rank(person),
                -(getattr(person, "usefulness_score", None) or 0),
                _match_rank(getattr(person, "match_quality", None)),
                _org_rank(bucket, getattr(person, "org_level", "ic") or "ic"),
                _confidence_rank(getattr(person, "company_match_confidence", None)),
                0 if person.linkedin_url else 1,
                _normalize_identity(person.full_name),
            )
        )
        finalized[bucket] = ordered
    deduped = _dedupe_bucket_assignments(finalized)
    return {
        bucket: people[:target_count_per_bucket]
        for bucket, people in deduped.items()
    }


def _detached_person_copy(person: Person) -> Person:
    """Clone a Person for cross-bucket display without sharing ORM state.

    ``copy.copy`` on a mapped instance shares ``_sa_instance_state`` with the
    original, so the session would treat the clone as the same persistent row
    (audit M10). Constructing a fresh ``Person`` gives the clone its own state;
    we then copy over loaded column values and dynamic ranking attributes. The
    clone is never added to the session, so it stays transient.

    Mutable container attributes (``profile_data``/``github_data``) are deep-copied
    so mutating the clone can never corrupt the original peer's data (audit
    pass-2 P12).
    """
    clone = Person()
    mutable_keys = {"profile_data", "github_data"}
    for key, value in person.__dict__.items():
        if key == "_sa_instance_state":
            continue
        if key in mutable_keys and isinstance(value, (dict, list)):
            clone.__dict__[key] = copy.deepcopy(value)
        else:
            clone.__dict__[key] = value
    return clone


def _backfill_sparse_hiring_manager_bucket(
    bucketed: dict[str, list[Person]],
    *,
    target_count_per_bucket: int,
) -> None:
    if len(bucketed.get("hiring_managers", [])) >= target_count_per_bucket:
        return

    existing_ids = {person.id for person in bucketed.get("hiring_managers", []) if person.id}
    for person in bucketed.get("peers", []):
        if person.id in existing_ids:
            continue
        confidence = _company_match_confidence(person)
        if confidence not in {"verified", "strong_signal"}:
            continue
        if not (_is_senior_ic_fallback(person.title) or getattr(person, "org_level", None) in {"manager", "director_plus"}):
            continue

        fallback_person = _detached_person_copy(person)
        fallback_person.person_type = "hiring_manager"
        fallback_person.match_quality = "next_best"
        fallback_person.match_reason = "Senior IC fallback at the target company."
        fallback_person.fallback_reason = "Senior IC fallback at the target company."
        fallback_person.org_level = getattr(person, "org_level", None) or "ic"
        # Mark as a deliberate cross-bucket clone so id-based dedup keeps it in
        # hiring_managers instead of discarding it in favor of the original peer
        # (audit pass-2 P8 — this backfill was otherwise dead code).
        fallback_person._synthetic_fallback = True  # type: ignore[attr-defined]
        bucketed["hiring_managers"].append(fallback_person)
        existing_ids.add(fallback_person.id)
        if len(bucketed["hiring_managers"]) >= target_count_per_bucket:
            return
