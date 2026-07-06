"""Serialize people-search results into API response models.

Extracted from the people router so both the request handler and the
background snapshot-refresh Celery task build identical response/snapshot
shapes from one source of truth.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm.attributes import NO_VALUE

from app.schemas.linkedin_graph import LinkedInGraphConnectionResponse
from app.schemas.people import (
    CompanyResponse,
    PeopleSearchResponse,
    PersonResponse,
    SearchErrorDetail,
)


def _is_mock_value(value: object) -> bool:
    return value.__class__.__module__.startswith("unittest.mock")


def _safe_value(value):
    return None if _is_mock_value(value) else value


def _loaded_company(person) -> object | None:
    try:
        state = sa_inspect(person)
        loaded_value = state.attrs.company.loaded_value
        if loaded_value is not NO_VALUE and not _is_mock_value(loaded_value):
            return loaded_value
        explicit_company = getattr(person, "__dict__", {}).get("company")
        return explicit_company
    except Exception:
        return getattr(person, "__dict__", {}).get("company", getattr(person, "company", None))


def _serialize_company(company) -> CompanyResponse | None:
    if not company:
        return None
    payload = {field: getattr(company, field, None) for field in CompanyResponse.model_fields}
    return CompanyResponse(**payload)


def _serialize_linkedin_graph_connection(connection) -> LinkedInGraphConnectionResponse | None:
    if not connection:
        return None
    if isinstance(connection, dict):
        return LinkedInGraphConnectionResponse(**connection)

    payload = {
        "id": str(_safe_value(getattr(connection, "id", "")) or ""),
        "display_name": _safe_value(getattr(connection, "display_name", None)),
        "headline": _safe_value(getattr(connection, "headline", None)),
        "current_company_name": _safe_value(getattr(connection, "current_company_name", None)),
        "linkedin_url": _safe_value(getattr(connection, "linkedin_url", None)),
        "company_linkedin_url": _safe_value(getattr(connection, "company_linkedin_url", None)),
        "source": _safe_value(getattr(connection, "source", "manual_import")) or "manual_import",
        "last_synced_at": _safe_value(getattr(connection, "last_synced_at", None)),
    }
    if not payload["display_name"]:
        return None
    return LinkedInGraphConnectionResponse(**payload)


def _serialize_person(person) -> PersonResponse:
    payload = {}
    for field, field_info in PersonResponse.model_fields.items():
        if field in {"company", "warm_path_connection"}:
            continue
        value = _safe_value(getattr(person, field, None))
        if value is None and not field_info.is_required():
            continue
        payload[field] = value
    payload["company"] = _serialize_company(_loaded_company(person))
    warm_path_connection = _serialize_linkedin_graph_connection(
        getattr(person, "warm_path_connection", None)
    )
    if warm_path_connection is not None:
        payload["warm_path_connection"] = warm_path_connection
    # Corroboration lives in profile_data (JSON), not a column — surface it as
    # a first-class response field when >= 2 independent sources agreed.
    profile_data = _safe_value(getattr(person, "profile_data", None))
    if isinstance(profile_data, dict):
        corroborated = profile_data.get("corroborated_by")
        if isinstance(corroborated, list) and len(corroborated) >= 2:
            payload["corroborated_by"] = [str(s) for s in corroborated]
    return PersonResponse(**payload)


def _serialize_people_search_result(result: dict) -> PeopleSearchResponse:
    raw_errors = result.get("errors")
    errors = (
        [SearchErrorDetail(**e) for e in raw_errors]
        if raw_errors
        else None
    )
    return PeopleSearchResponse(
        company=_serialize_company(result.get("company")),
        your_connections=[
            LinkedInGraphConnectionResponse(**connection)
            for connection in result.get("your_connections", [])
        ],
        recruiters=[_serialize_person(person) for person in result.get("recruiters", [])],
        hiring_managers=[_serialize_person(person) for person in result.get("hiring_managers", [])],
        peers=[_serialize_person(person) for person in result.get("peers", [])],
        job_context=result.get("job_context"),
        errors=errors,
        debug=result.get("debug"),
    )


def _company_from_people(*buckets: list[PersonResponse]) -> CompanyResponse | None:
    """Recover the top-level company from the first person that carries one.

    Snapshots store only ``company_name`` at the top level, but every persisted
    person dict carries the full company (with id), so we lift it from there.
    """
    for bucket in buckets:
        for person in bucket:
            if person.company is not None:
                return person.company
    return None


def snapshot_to_search_response(snapshot: Any) -> PeopleSearchResponse:
    """Rebuild a PeopleSearchResponse from a stored JobResearchSnapshot.

    The snapshot persists ``model_dump(mode="json")`` person/connection dicts,
    so they round-trip straight back into the response models.
    """
    recruiters = [PersonResponse(**p) for p in (snapshot.recruiters or [])]
    hiring_managers = [PersonResponse(**p) for p in (snapshot.hiring_managers or [])]
    peers = [PersonResponse(**p) for p in (snapshot.peers or [])]
    your_connections = [
        LinkedInGraphConnectionResponse(**c) for c in (snapshot.your_connections or [])
    ]
    errors = (
        [SearchErrorDetail(**e) for e in snapshot.errors]
        if snapshot.errors
        else None
    )
    return PeopleSearchResponse(
        company=_company_from_people(recruiters, hiring_managers, peers),
        your_connections=your_connections,
        recruiters=recruiters,
        hiring_managers=hiring_managers,
        peers=peers,
        job_context=None,
        errors=errors,
        debug=None,
        served_from_snapshot=True,
    )
