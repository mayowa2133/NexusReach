"""Deterministic structured job requirements and user-eligibility evaluation.

The same versioned schema is consumed by job match scoring and resume quality.
It keeps mandatory qualifications separate from preferences and responsibilities,
retains the source span that justified each extraction, and models hard constraints
without pretending an unknown user attribute is a confirmed mismatch.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Literal

from app.utils.job_metadata import country_code_for_name


REQUIREMENT_SCHEMA_VERSION = 1

RequirementKind = Literal["mandatory", "preferred", "responsibility"]
EvidenceType = Literal[
    "skill",
    "credential",
    "education",
    "experience",
    "work_authorization",
    "language",
    "schedule",
    "travel",
    "clearance",
    "license",
    "portfolio",
    "contract",
    "salary",
]
Criticality = Literal["hard", "important", "supporting"]


@dataclass(frozen=True)
class JobRequirement:
    id: str
    normalized: str
    display_text: str
    kind: RequirementKind
    evidence_type: EvidenceType
    criticality: Criticality
    source_span: str
    confidence: float
    value: str | int | float | bool | None = None
    version: int = REQUIREMENT_SCHEMA_VERSION

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "normalized": self.normalized,
            "display_text": self.display_text,
            "kind": self.kind,
            "evidence_type": self.evidence_type,
            "criticality": self.criticality,
            "source_span": self.source_span,
            "confidence": self.confidence,
            "value": self.value,
            "version": self.version,
        }


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool | None
    hard_failures: tuple[dict, ...]
    unknown_constraints: tuple[dict, ...]
    matched_constraints: tuple[dict, ...]
    excluded_by: tuple[str, ...] = ()
    version: int = REQUIREMENT_SCHEMA_VERSION

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "eligible": self.eligible,
            "hard_failures": list(self.hard_failures),
            "unknown_constraints": list(self.unknown_constraints),
            "matched_constraints": list(self.matched_constraints),
            "excluded_by": list(self.excluded_by),
        }


_TAG_RE = re.compile(r"<[^>]+>")
_MANDATORY_HEADER_RE = re.compile(
    r"^(?:minimum |basic )?(?:requirements?|qualifications?|must[- ]haves?)\s*:? *$",
    re.I,
)
_PREFERRED_HEADER_RE = re.compile(
    r"^(?:preferred qualifications?|nice[- ]to[- ]haves?|bonus|desired)\s*:? *$",
    re.I,
)
_RESPONSIBILITY_HEADER_RE = re.compile(
    r"^(?:responsibilities|what you(?:'ll| will) do|the role|duties)\s*:? *$",
    re.I,
)
_MANDATORY_CUE_RE = re.compile(
    r"\b(?:must|required|requirement|minimum|need to|shall|mandatory)\b",
    re.I,
)
_PREFERRED_CUE_RE = re.compile(
    r"\b(?:preferred|nice to have|bonus|ideally|a plus|desired)\b",
    re.I,
)

_TYPED_PATTERNS: tuple[
    tuple[str, EvidenceType, str, re.Pattern[str], Criticality], ...
] = (
    ("CPA", "credential", "CPA", re.compile(r"\bCPA\b", re.I), "hard"),
    ("PMP", "credential", "PMP", re.compile(r"\bPMP\b", re.I), "important"),
    ("CISSP", "credential", "CISSP", re.compile(r"\bCISSP\b", re.I), "important"),
    ("RN license", "license", "RN license", re.compile(
        r"\b(?:(?:active|valid|current)\s+)?(?:RN|registered nurse)(?:\s+license|\s+licen[cs]ure|\s+registration)\b",
        re.I,
    ), "hard"),
    ("bar admission", "license", "bar admission", re.compile(
        r"\b(?:bar admission|admitted to (?:the )?bar|licensed attorney)\b", re.I
    ), "hard"),
    ("driver's license", "license", "driver's license", re.compile(
        r"\b(?:valid\s+)?driver'?s? licen[cs]e\b", re.I
    ), "hard"),
    ("security clearance", "clearance", "security clearance", re.compile(
        r"\b(?:(?:active|current)\s+)?(?:(?:top )?secret|security) clearance\b", re.I
    ), "hard"),
    ("portfolio", "portfolio", "portfolio", re.compile(
        r"\b(?:portfolio|work samples?|writing samples?)\b", re.I
    ), "important"),
    ("degree", "education", "degree", re.compile(
        r"\b(?:bachelor'?s?|master'?s?|doctorate|ph\.?d\.?|college|university)\s+(?:degree|in)\b|\bdegree in\b",
        re.I,
    ), "important"),
    ("work authorization", "work_authorization", "work authorization", re.compile(
        r"\b(?:authorized|eligible) to work\b|\bwork authorization\b", re.I
    ), "hard"),
    ("no sponsorship", "work_authorization", "no sponsorship", re.compile(
        r"\b(?:unable to|cannot|can not|will not|do not)\s+(?:provide|offer)\s+(?:visa\s+)?sponsorship\b|\bno sponsorship\b",
        re.I,
    ), "hard"),
    ("shift work", "schedule", "shift work", re.compile(
        r"\b(?:night|evening|weekend|rotating|overnight) shifts?\b|\bshift work\b", re.I
    ), "hard"),
    ("on-call", "schedule", "on-call", re.compile(r"\bon[- ]call\b", re.I), "hard"),
    ("contract", "contract", "contract", re.compile(
        r"\b(?:fixed[- ]term|temporary|contract)(?:\s+(?:role|position|duration))?\b", re.I
    ), "important"),
)

_YEARS_RE = re.compile(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\b", re.I)
_TRAVEL_RE = re.compile(r"\b(?:travel\s+(?:up to\s+)?)?(\d{1,3})\s*%\s+(?:travel|required)\b", re.I)
_LANGUAGE_RE = re.compile(
    r"\b(?:fluent|fluency|proficient|proficiency|bilingual)\s+(?:in\s+)?"
    r"(English|French|Spanish|German|Mandarin|Cantonese|Portuguese|Arabic|Hindi|Japanese|Korean)\b",
    re.I,
)
_CONTRACT_DURATION_PATTERNS = (
    re.compile(
        r"\b(?P<count>\d{1,3})\s*[- ]?\s*(?P<unit>weeks?|months?|years?)\b"
        r"(?=.{0,30}\b(?:contract|fixed[- ]term|temporary)\b)",
        re.I,
    ),
    re.compile(
        r"\b(?:contract|fixed[- ]term|temporary)\b.{0,30}?"
        r"(?P<count>\d{1,3})\s*[- ]?\s*(?P<unit>weeks?|months?|years?)\b",
        re.I,
    ),
)

_CAPABILITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.I))
    for label, pattern in (
        ("Python", r"\bPython\b"),
        ("JavaScript", r"\b(?:JavaScript|JS)\b"),
        ("TypeScript", r"\b(?:TypeScript|TS)\b"),
        ("SQL", r"\bSQL\b"),
        ("Excel", r"\b(?:Microsoft )?Excel\b"),
        ("SAP", r"\bSAP\b"),
        ("Salesforce", r"\bSalesforce\b"),
        ("SEO", r"\bSEO\b"),
        ("Google Analytics", r"\b(?:Google Analytics|GA4)\b"),
        ("financial reporting", r"\bfinancial reporting\b"),
        ("forecasting", r"\bforecast(?:ing|s)?\b"),
        ("budgeting", r"\bbudget(?:ing|s)?\b"),
        ("audit", r"\baudit(?:ing|s)?\b"),
        ("patient care", r"\bpatient care\b"),
        ("electronic health records", r"\b(?:electronic health records?|EHR|EMR)\b"),
        ("curriculum design", r"\bcurriculum (?:design|development)\b"),
        ("classroom management", r"\bclassroom management\b"),
        ("litigation", r"\blitigation\b"),
        ("contract drafting", r"\bcontract (?:drafting|negotiation)\b"),
        ("quota attainment", r"\b(?:quota attainment|achieve quota|sales quota)\b"),
        ("CRM", r"\bCRM\b"),
        ("procurement", r"\bprocurement\b"),
        ("inventory management", r"\binventory (?:management|planning)\b"),
        ("project management", r"\bproject management\b"),
        ("Agile", r"\bAgile\b"),
        ("CAD", r"\bCAD\b"),
        ("SolidWorks", r"\bSolidWorks\b"),
        ("Tableau", r"\bTableau\b"),
        ("Power BI", r"\bPower\s*BI\b"),
        ("data analysis", r"\bdata (?:analysis|analytics)\b"),
        ("machine learning", r"\bmachine learning\b"),
        ("AWS", r"\bAWS\b|\bAmazon Web Services\b"),
        ("Kubernetes", r"\bKubernetes\b|\bK8s\b"),
        ("React", r"\bReact(?:\.js|JS)?\b"),
    )
)


def _plain_lines(description: str | None) -> list[str]:
    text = html.unescape(description or "")
    text = re.sub(r"(?i)</?(?:p|li|ul|ol|br|h[1-6]|div)[^>]*>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    lines: list[str] = []
    for raw in text.splitlines():
        cleaned = re.sub(r"^[\s\-•*\d.)]+", "", raw).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned:
            lines.append(cleaned[:1000])
    return lines


def _kind_for_line(line: str, section: RequirementKind) -> RequirementKind:
    if _PREFERRED_CUE_RE.search(line):
        return "preferred"
    if _MANDATORY_CUE_RE.search(line):
        return "mandatory"
    return section


def _requirement_id(evidence_type: EvidenceType, normalized: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")
    return f"{evidence_type}:{slug}"


def extract_job_requirements(description: str | None) -> list[JobRequirement]:
    """Extract a stable, deduplicated requirement set from a job description."""
    section: RequirementKind = "responsibility"
    extracted: dict[str, JobRequirement] = {}
    for line in _plain_lines(description):
        if _MANDATORY_HEADER_RE.match(line):
            section = "mandatory"
            continue
        if _PREFERRED_HEADER_RE.match(line):
            section = "preferred"
            continue
        if _RESPONSIBILITY_HEADER_RE.match(line):
            section = "responsibility"
            continue
        kind = _kind_for_line(line, section)

        def add(
            normalized: str,
            display: str,
            evidence_type: EvidenceType,
            criticality: Criticality,
            confidence: float,
            value: str | int | float | bool | None = None,
        ) -> None:
            requirement_kind = kind
            effective_criticality = criticality
            if requirement_kind == "preferred" and criticality == "hard":
                effective_criticality = "important"
            req_id = _requirement_id(evidence_type, normalized)
            candidate = JobRequirement(
                id=req_id,
                normalized=normalized,
                display_text=display,
                kind=requirement_kind,
                evidence_type=evidence_type,
                criticality=effective_criticality,
                source_span=line,
                confidence=confidence,
                value=value,
            )
            existing = extracted.get(req_id)
            kind_rank = {"responsibility": 0, "preferred": 1, "mandatory": 2}
            if existing is None or kind_rank[candidate.kind] > kind_rank[existing.kind]:
                extracted[req_id] = candidate

        for normalized, evidence_type, display, pattern, criticality in _TYPED_PATTERNS:
            if pattern.search(line):
                add(normalized, display, evidence_type, criticality, 0.95)

        years = _YEARS_RE.search(line)
        if years and re.search(r"\bexperience\b", line, re.I):
            count = int(years.group(1))
            add(
                f"{count}+ years experience",
                f"{count}+ years of experience",
                "experience",
                "hard" if kind == "mandatory" else "important",
                0.95,
                count,
            )

        travel = _TRAVEL_RE.search(line)
        if travel:
            percent = min(100, int(travel.group(1)))
            add(
                f"travel {percent}%",
                f"Up to {percent}% travel",
                "travel",
                "hard",
                0.95,
                percent,
            )

        for language in _LANGUAGE_RE.findall(line):
            normalized_language = language.title()
            add(
                f"{normalized_language} language",
                f"{normalized_language} proficiency",
                "language",
                "hard" if kind == "mandatory" else "important",
                0.9,
                normalized_language,
            )

        for duration_pattern in _CONTRACT_DURATION_PATTERNS:
            duration = duration_pattern.search(line)
            if not duration:
                continue
            count = int(duration.group("count"))
            unit = duration.group("unit").lower()
            months = (
                max(1, round(count / 4.345))
                if unit.startswith("week")
                else count * 12 if unit.startswith("year") else count
            )
            add(
                f"contract duration {months} months",
                f"{months}-month contract",
                "contract",
                "hard" if kind == "mandatory" else "important",
                0.95,
                months,
            )
            break

        for label, pattern in _CAPABILITY_PATTERNS:
            if pattern.search(line):
                add(
                    label,
                    label,
                    "skill",
                    "important" if kind != "responsibility" else "supporting",
                    0.9,
                )

    return list(extracted.values())


def requirement_terms(
    requirements: list[JobRequirement],
    *,
    include_responsibilities: bool = True,
) -> list[str]:
    return list(dict.fromkeys(
        requirement.normalized
        for requirement in requirements
        if include_responsibilities or requirement.kind != "responsibility"
    ))


def _term_present(text: str, term: str) -> bool:
    normalized_text = re.sub(r"\s+", " ", text.lower())
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", normalized_text))


def evaluate_job_eligibility(
    *,
    job_data: dict,
    requirements: list[JobRequirement],
    evidence_text: str,
    preferences: dict | None,
    evidence_available: bool = True,
) -> EligibilityDecision:
    """Evaluate explicit hard constraints; preserve unknowns as unknown.

    ``eligible=False`` is returned only for a confirmed contradiction or a
    missing credential/license/clearance that the posting explicitly marks as
    mandatory. Unknown authorization/schedule data never becomes a fabricated
    pass or fail.
    """
    preferences = preferences if isinstance(preferences, dict) else {}
    hard_failures: list[dict] = []
    unknown: list[dict] = []
    matched: list[dict] = []
    excluded_by: list[str] = []
    company = str(job_data.get("company_name") or "")
    title = str(job_data.get("title") or "")
    full_job_text = f"{title}\n{job_data.get('description') or ''}"

    excluded_employers = {
        str(value).strip().casefold()
        for value in preferences.get("excluded_employers") or []
        if str(value).strip()
    }
    if company.strip().casefold() in excluded_employers:
        excluded_by.append(f"excluded_employer:{company}")
    for keyword in preferences.get("blocked_keywords") or []:
        cleaned = str(keyword).strip()
        if cleaned and _term_present(full_job_text, cleaned):
            excluded_by.append(f"blocked_keyword:{cleaned}")

    authorization_codes: set[str] = set()
    for value in preferences.get("work_authorization_countries") or []:
        cleaned = str(value).strip()
        code = country_code_for_name(cleaned)
        if not code and len(cleaned) == 2 and cleaned.isalpha():
            code = cleaned
        if code:
            authorization_codes.add(code.upper())
    job_country_codes = {
        str(value).strip().upper()
        for value in job_data.get("country_codes") or []
        if str(value).strip()
    }
    if authorization_codes and job_country_codes and authorization_codes.isdisjoint(job_country_codes):
        excluded_by.append(
            "work_authorization_country:" + ",".join(sorted(job_country_codes))
        )

    evidence = f"{evidence_text}\n{' '.join(map(str, preferences.get('licenses') or []))}\n"
    evidence += " ".join(map(str, preferences.get("clearances") or []))
    languages = {
        str(value).strip().casefold()
        for value in preferences.get("languages") or []
        if str(value).strip()
    }
    allowed_schedules = {
        str(value).strip().casefold()
        for value in preferences.get("allowed_schedules") or []
        if str(value).strip()
    }
    max_travel = preferences.get("max_travel_percent")

    def preference_constraint(
        constraint_id: str,
        display_text: str,
        evidence_type: EvidenceType,
        value: str | int | float | bool | None,
    ) -> dict:
        return {
            "id": f"preference:{constraint_id}",
            "normalized": constraint_id.replace("_", " "),
            "display_text": display_text,
            "kind": "mandatory",
            "evidence_type": evidence_type,
            "criticality": "hard",
            "source_span": "User job preferences",
            "confidence": 1.0,
            "value": value,
            "version": REQUIREMENT_SCHEMA_VERSION,
        }

    required_currency = str(preferences.get("required_salary_currency") or "").strip().upper()
    salary_currency = str(job_data.get("salary_currency") or "").strip().upper()
    salary_present = job_data.get("salary_min") is not None or job_data.get("salary_max") is not None
    if required_currency:
        item = preference_constraint(
            "required_salary_currency",
            f"Salary must be reported in {required_currency}",
            "salary",
            required_currency,
        )
        if salary_currency:
            (matched if salary_currency == required_currency else hard_failures).append(item)
        else:
            unknown.append(item)

    required_period = str(preferences.get("required_salary_period") or "").strip().lower()
    salary_period = str(job_data.get("salary_period") or "").strip().lower()
    if required_period:
        item = preference_constraint(
            "required_salary_period",
            f"Salary must be reported per {required_period}",
            "salary",
            required_period,
        )
        if salary_period:
            (matched if salary_period == required_period else hard_failures).append(item)
        else:
            unknown.append(item)

    minimum_salary_confidence = preferences.get("minimum_salary_confidence")
    if isinstance(minimum_salary_confidence, (int, float)):
        item = preference_constraint(
            "minimum_salary_confidence",
            f"Salary confidence must be at least {float(minimum_salary_confidence):.2f}",
            "salary",
            float(minimum_salary_confidence),
        )
        salary_provenance = (
            job_data.get("metadata_provenance", {}).get("salary", {})
            if isinstance(job_data.get("metadata_provenance"), dict)
            else {}
        )
        confidence = salary_provenance.get("confidence") if isinstance(salary_provenance, dict) else None
        if not salary_present or not isinstance(confidence, (int, float)):
            unknown.append(item)
        elif float(confidence) < float(minimum_salary_confidence):
            hard_failures.append(item)
        else:
            matched.append(item)

    minimum_contract_months = preferences.get("minimum_contract_months")
    is_contract = str(job_data.get("employment_type") or "").strip().lower() == "contract" or any(
        requirement.evidence_type == "contract" for requirement in requirements
    )
    if isinstance(minimum_contract_months, int) and is_contract:
        item = preference_constraint(
            "minimum_contract_months",
            f"Contract must be at least {minimum_contract_months} months",
            "contract",
            minimum_contract_months,
        )
        durations = [
            int(requirement.value)
            for requirement in requirements
            if requirement.evidence_type == "contract"
            and isinstance(requirement.value, (int, float))
        ]
        if not durations:
            unknown.append(item)
        elif max(durations) < minimum_contract_months:
            hard_failures.append(item)
        else:
            matched.append(item)

    for requirement in requirements:
        if requirement.criticality != "hard" or requirement.kind != "mandatory":
            continue
        item = requirement.as_dict()
        if requirement.evidence_type in {"credential", "license", "clearance"}:
            if _term_present(evidence, requirement.normalized) or _term_present(
                evidence, requirement.display_text
            ):
                matched.append(item)
            elif evidence_available:
                hard_failures.append(item)
            else:
                unknown.append(item)
        elif requirement.evidence_type == "language":
            language = str(requirement.value or "").casefold()
            if language and (language in languages or _term_present(evidence, language)):
                matched.append(item)
            elif languages:
                hard_failures.append(item)
            else:
                unknown.append(item)
        elif requirement.evidence_type == "travel":
            if isinstance(max_travel, (int, float)):
                if float(requirement.value or 0) <= float(max_travel):
                    matched.append(item)
                else:
                    hard_failures.append(item)
            else:
                unknown.append(item)
        elif requirement.evidence_type == "schedule":
            schedule = str(requirement.normalized).casefold()
            if allowed_schedules:
                if schedule in allowed_schedules:
                    matched.append(item)
                else:
                    hard_failures.append(item)
            else:
                unknown.append(item)
        elif requirement.evidence_type == "work_authorization":
            requires_sponsorship = preferences.get("requires_sponsorship")
            if requirement.normalized == "no sponsorship" and requires_sponsorship is True:
                hard_failures.append(item)
            elif requires_sponsorship is None:
                unknown.append(item)
            else:
                matched.append(item)

    if excluded_by or hard_failures:
        eligible: bool | None = False
    elif unknown:
        eligible = None
    else:
        eligible = True
    return EligibilityDecision(
        eligible=eligible,
        hard_failures=tuple(hard_failures),
        unknown_constraints=tuple(unknown),
        matched_constraints=tuple(matched),
        excluded_by=tuple(excluded_by),
    )
