"""Title predicates, keyword constants, and search-title generators for people discovery."""

import logging
import re


from app.utils.job_context import (
    JobContext,
)
from app.services.occupation_taxonomy import (
    manager_title_seeds_for as _occupation_manager_titles,
    peer_title_seeds_for as _occupation_peer_titles,
)

from app.services.people.identity import _contains_any_keyword, _identity_tokens, _keyword_in_text, _normalize_identity, _public_profile_url
logger = logging.getLogger(__name__)


RECRUITER_TITLE_KEYWORDS = (
    "recruiter",
    "hiring coordinator",
    "hiring",
    "recruiting",
    "recruiting coordinator",
    "recruiting partner",
    "recruitment",
    "talent acquisition",
    "talent operations",
    "talent partner",
    "talent scout",
    "sourcer",
    "technical sourcer",
    "campus recruiter",
    "university recruiter",
    "early careers",
    "early talent",
    "emerging talent",
    "university programs",
)


GENERIC_PEOPLE_TITLE_KEYWORDS = (
    "human resources",
    "people operations",
    "people ops",
    "people partner",
    "hr business partner",
    "hrbp",
)


MANAGER_TITLE_KEYWORDS = (
    "manager",
    "director",
    "head",
    "vice president",
    "vp",
    # Startup hiring contacts: founders and chiefs lead the teams that hire.
    "founder",
    "chief",
)


CONTROLLED_LEAD_KEYWORDS = (
    "tech lead",
    "team lead",
    "engineering lead",
)


DIRECTOR_PLUS_KEYWORDS = (
    "director",
    "head",
    "vice president",
    "vp",
    "managing director",
    "chief",
)


_FOUNDER_EXEC_TITLE_RE = re.compile(
    r"\b(co[- ]?founder|founder|founding|cto|ceo|coo|cpo"
    r"|chief\s+\w+(\s+\w+)?\s+officer|chief\s+(technology|executive|operating|product|people))\b",
    re.IGNORECASE,
)


def _is_founder_exec_title(title: str | None) -> bool:
    """True for founder / C-level titles - the de-facto hiring managers at startups."""
    return bool(title) and bool(_FOUNDER_EXEC_TITLE_RE.search(title))


ROLE_HINT_KEYWORDS = (
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "recruiter",
    "talent",
    "sourcer",
    "manager",
    "director",
    "lead",
    "partner",
    # Founder/executive titles: at small startups these ARE the hiring
    # contacts, and without them the company gate rejects founders outright.
    "founder",
    "chief",
    "head",
    "officer",
    "president",
    "principal",
    "vp",
)


SENIOR_MANAGER_LEVELS = {"staff", "principal", "manager", "director", "vp", "executive"}


WEAK_TITLE_PLACEHOLDERS = {
    "employee",
    "member",
    "team member",
    "staff member",
    "teammate",
}


RECRUITER_ADJACENT_KEYWORDS = (
    "talent acquisition",
    "talent operations",
    "talent partner",
    "early talent",
    "early careers",
    "university programs",
    "recruiting coordinator",
    "recruitment",
)


SENIOR_IC_FALLBACK_KEYWORDS = (
    "staff engineer",
    "principal engineer",
    "member of technical staff",
    "technical staff",
    "architect",
)


TALENT_TITLE_KEYWORDS = (
    "talent",
    "sourcer",
    "sourcing",
    "talent partner",
    "talent operations",
    "talent coordinator",
    "people partner",
    "employer brand",
)


SENIORITY_ORDER = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "staff": 4,
    "principal": 4,
    "lead": 3,
    "manager": 5,
    "director": 6,
    "vp": 7,
    "executive": 8,
}


def _role_like_title(title: str) -> bool:
    normalized = _normalize_identity(title)
    return any(keyword in normalized for keyword in ROLE_HINT_KEYWORDS)


def _title_looks_like_company_only(title: str, company_name: str) -> bool:
    normalized_title = _normalize_identity(title)
    normalized_company = _normalize_identity(company_name)
    if not normalized_title or not normalized_company:
        return False
    if normalized_title == normalized_company:
        return True

    title_tokens = _identity_tokens(normalized_title)
    company_tokens = _identity_tokens(normalized_company)
    if not title_tokens or not company_tokens:
        return False
    suffixes = {"inc", "llc", "lp", "l.p", "ltd", "limited", "corp", "corporation", "co"}
    filtered_title = [token for token in title_tokens if token not in suffixes]
    return filtered_title == company_tokens


def _title_is_weak(title: str | None, company_name: str) -> bool:
    normalized_title = _normalize_identity(title)
    if not normalized_title:
        return True
    if normalized_title in WEAK_TITLE_PLACEHOLDERS:
        return True
    return _title_looks_like_company_only(normalized_title, company_name)


def _is_recruiter_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    if not _contains_any_keyword(normalized, RECRUITER_TITLE_KEYWORDS):
        return False
    generic_only = _contains_any_keyword(normalized, GENERIC_PEOPLE_TITLE_KEYWORDS) and not any(
        keyword in normalized for keyword in ("recruit", "talent acquisition", "talent operations", "talent partner", "sourcer", "early talent", "early careers", "emerging talent", "university", "hiring")
    )
    return not generic_only


def _is_manager_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    return _contains_any_keyword(normalized, MANAGER_TITLE_KEYWORDS + CONTROLLED_LEAD_KEYWORDS)


def _generic_manager_title(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    return normalized in {"manager", "director", "head", "vice president", "vp"}


def _manager_candidate_has_engineering_context(data: dict, *, context: JobContext | None) -> bool:
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    location = data.get("location", "") or profile_data.get("location", "") or ""
    result_title = profile_data.get("linkedin_result_title", "") or ""
    public_snippet = profile_data.get("public_snippet", "") or ""
    haystack = " ".join(part for part in [title, snippet, result_title, public_snippet, location] if part).lower()

    if any(keyword in haystack for keyword in ("engineering", "software", "developer", "full stack", "fullstack", "platform")):
        return True
    if context:
        keywords = list(dict.fromkeys((context.team_keywords or []) + (context.domain_keywords or [])))
        if any(_keyword_in_text(keyword.lower(), haystack) for keyword in keywords if keyword):
            return True
    return False


def _is_adjacent_recruiter_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in RECRUITER_ADJACENT_KEYWORDS)


def _is_senior_ic_fallback(title: str | None) -> bool:
    normalized = _normalize_identity(title)
    if not normalized:
        return False
    if normalized.startswith("senior ") and any(role in normalized for role in ("engineer", "scientist", "developer")):
        return True
    return any(keyword in normalized for keyword in SENIOR_IC_FALLBACK_KEYWORDS)


def _strip_seniority_prefix(title: str | None) -> str:
    cleaned = (title or "").strip()
    cleaned = re.sub(
        r"^(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|associate|entry[- ]level|new grad(?:uate)?|intern)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+\b(i|ii|iii|iv)\b$", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()


_IC_MANAGER_PATTERNS = (
    r"\bproduct manager\b",
    r"\bprogram manager\b",
    r"\bproject manager\b",
    r"\baccount manager\b",
    r"\bcommunity manager\b",
    r"\bcontent manager\b",
    r"\bcampaign manager\b",
    r"\bpartnership manager\b",
    r"\bsuccess manager\b",
    r"\brelationship manager\b",
)


def _candidate_seniority_level(data: dict) -> str:
    explicit = _normalize_identity(str(data.get("seniority") or ""))
    if explicit in SENIORITY_ORDER:
        return explicit

    haystack = " ".join(
        part for part in [data.get("title", ""), data.get("snippet", "")]
        if part
    ).lower()

    # Check for IC "manager" roles first — these should be sized by their
    # own seniority prefix (Senior PM → senior, Associate PM → junior),
    # NOT treated as people-managers.
    is_ic_manager = any(re.search(p, haystack) for p in _IC_MANAGER_PATTERNS)

    patterns = (
        (r"\bintern\b", "intern"),
        (r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bassociate\b|\bnew grad\b|\bapm\b", "junior"),
        (r"\bsenior\b|\bsr\.?\b", "senior"),
        (r"\bstaff\b", "staff"),
        (r"\bprincipal\b", "principal"),
        (r"\blead\b", "lead"),
        (r"\bengineering manager\b", "manager"),
        (r"\bdirector\b", "director"),
        (r"\bvp\b|\bvice president\b", "vp"),
        (r"\bchief\b|\bc-level\b", "executive"),
    )
    for pattern, level in patterns:
        if re.search(pattern, haystack):
            return level

    # Bare "manager" — only counts as people-manager if NOT an IC title
    if re.search(r"\bmanager\b", haystack):
        return "mid" if is_ic_manager else "manager"

    return "mid"


def _peer_title_variants_for_seniority(title: str, seniority: str) -> tuple[list[str], list[str]]:
    base_title = _strip_seniority_prefix(title)
    if not base_title:
        return [], []

    same_level: list[str]
    adjacent_level: list[str]

    if seniority == "intern":
        same_level = [f"{base_title} Intern", "Software Engineering Intern", base_title]
        adjacent_level = [f"Junior {base_title}", f"Associate {base_title}"]
    elif seniority == "junior":
        same_level = [
            f"Junior {base_title}",
            f"Associate {base_title}",
            f"Entry Level {base_title}",
            f"{base_title} I",
            base_title,
        ]
        adjacent_level = [f"Mid-Level {base_title}", f"Senior {base_title}"]
    elif seniority == "senior":
        same_level = [f"Senior {base_title}", base_title]
        adjacent_level = [f"Staff {base_title}", f"Principal {base_title}"]
    elif seniority in {"staff", "principal"}:
        same_level = [f"Staff {base_title}", f"Principal {base_title}", f"Senior {base_title}"]
        adjacent_level = [base_title]
    else:
        same_level = [base_title]
        adjacent_level = [f"Junior {base_title}", f"Senior {base_title}", f"Associate {base_title}"]

    def _dedupe_variants(values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for variant in values:
            normalized = _normalize_identity(variant)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(variant)
        return ordered

    return _dedupe_variants(same_level), _dedupe_variants(adjacent_level)


def _prioritize_titles_for_search(
    titles: list[str],
    *,
    bucket: str,
    context: JobContext | None,
) -> list[str]:
    normalized_titles = list(dict.fromkeys(title for title in titles if title))
    if not normalized_titles:
        return []

    def rank(title: str) -> tuple[int, str]:
        normalized = _normalize_identity(title)
        if bucket == "recruiters" and context and context.early_career:
            preferred_order = {
                "campus recruiter": 0,
                "university recruiter": 1,
                "early careers recruiter": 2,
                "early talent recruiter": 3,
                "university programs recruiter": 4,
                "recruiting coordinator": 5,
                "technical sourcer": 6,
                "talent acquisition partner": 7,
                "engineering recruiter": 8,
                "technical recruiter": 9,
                "talent acquisition": 10,
                "recruiter": 11,
            }
            return (preferred_order.get(normalized, 20), normalized)

        if bucket == "hiring_managers" and context and context.early_career and context.department == "engineering":
            preferred_order = {
                "engineering manager": 0,
                "software engineering manager": 1,
                "team lead": 2,
                "tech lead": 3,
                "technical lead": 4,
                "software engineer team lead": 5,
                "software engineer tech lead": 6,
                "software engineering lead": 7,
            }
            return (preferred_order.get(normalized, 20), normalized)

        return (10, normalized)

    return [title for _, title in sorted((rank(title), title) for title in normalized_titles)]


def _broaden_peer_titles_for_retry(context: JobContext | None) -> list[str]:
    if not context:
        return []

    prioritized = _prioritize_titles_for_search(
        context.peer_titles,
        bucket="peers",
        context=context,
    )
    # Canonical occupation peers lead every retry. Department-derived titles
    # are only breadth fallbacks and must never replace the user's profession.
    taxonomy_titles = (
        _occupation_peer_titles(context.occupation_keys)
        if context.occupation_keys else []
    )
    base_titles: list[str] = list(dict.fromkeys(prioritized + taxonomy_titles))
    ml_family_context = (
        "ml" in context.team_keywords
        or any(
            term in _normalize_identity(title)
            for title in prioritized
            for term in (
                "machine learning",
                "ml engineer",
                "applied scientist",
                "data scientist",
                "model training",
                "research engineer",
            )
        )
    )
    if context.department == "data_science" or ml_family_context:
        if "ml" in context.team_keywords or any(
            term in _normalize_identity(title)
            for title in prioritized
            for term in ("machine learning", "ml engineer", "applied scientist", "data scientist", "model training")
        ):
            base_titles = [
                "Machine Learning Engineer",
                "Software Engineer",
                "Applied Scientist",
                "Research Engineer",
                "Data Scientist",
                "Model Training Engineer",
                "Training Infrastructure Engineer",
                "Distributed Systems Engineer",
                *base_titles,
            ]
        else:
            base_titles = [
                "Data Scientist", "Research Engineer", "Software Engineer", *base_titles,
            ]
    elif context.department == "engineering":
        engineering_family = ["Software Engineer", "Software Developer"]
        if any(keyword in context.team_keywords for keyword in ("backend", "platform", "cloud", "devops")):
            engineering_family = [
                "Backend Engineer",
                "Platform Engineer",
                "Infrastructure Engineer",
                "Distributed Systems Engineer",
                *engineering_family,
            ]
        if any(keyword in context.team_keywords for keyword in ("frontend", "mobile")):
            engineering_family = [
                "Frontend Engineer",
                "UI Engineer",
                "Mobile Engineer",
                *engineering_family,
            ]
        base_titles.extend(engineering_family)
    elif context.department == "product_management":
        base_titles.extend(["Product Manager", "Technical Program Manager", "Program Manager"])
    elif context.department == "design":
        base_titles.extend(["Product Designer", "UX Designer", "UI Designer"])
    elif context.department == "information_technology":
        base_titles.extend(["Security Engineer", "IT Engineer", "Systems Engineer", "Network Engineer"])
    else:
        dept_label = context.department.replace("_", " ").title()
        base_titles.extend([f"{dept_label} Specialist", f"{dept_label} Analyst"])

    same_level_titles: list[str] = []
    adjacent_titles: list[str] = []
    seen: set[str] = set()
    for title in base_titles + prioritized:
        same_level_variants, adjacent_variants = _peer_title_variants_for_seniority(
            title,
            context.seniority,
        )
        for variant in same_level_variants + adjacent_variants:
            normalized = _normalize_identity(variant)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            if variant in same_level_variants:
                same_level_titles.append(variant)
            else:
                adjacent_titles.append(variant)
    return same_level_titles + adjacent_titles


def _companywide_recruiter_titles(context: JobContext | None) -> list[str]:
    if context:
        engineering_context = context.department == "engineering"
        titles = _prioritize_titles_for_search(
            context.recruiter_titles
            + [
                "Talent Acquisition Partner",
                "Recruiting Coordinator",
                "Recruitment Coordinator",
                "Talent Operations",
                "Early Career Programs",
                "Recruiter",
                "University Recruiter",
                "Campus Recruiter",
                "Emerging Talent Recruiter",
                "Early Career Recruiter",
                *(
                    ["Technical Recruiter", "Engineering Recruiter", "Technical Sourcer"]
                    if engineering_context else []
                ),
            ],
            bucket="recruiters",
            context=context,
        )
    else:
        titles = [
            "Technical Recruiter",
            "Engineering Recruiter",
            "Talent Acquisition Partner",
            "Technical Sourcer",
            "Recruiting Coordinator",
            "Recruitment Coordinator",
            "Talent Operations",
            "Early Career Programs",
            "Recruiter",
            "University Recruiter",
            "Campus Recruiter",
            "Emerging Talent Recruiter",
            "Early Career Recruiter",
        ]
    return list(dict.fromkeys(title for title in titles if title))


def _companywide_manager_titles(context: JobContext | None) -> list[str]:
    if context:
        taxonomy_titles = _occupation_manager_titles(
            context.occupation_keys, department=context.department
        )
        fallback = (
            ["Engineering Manager", "Software Engineering Manager", "Technical Lead", "Team Lead"]
            if context.department == "engineering" else []
        )
        titles = _prioritize_titles_for_search(
            context.manager_titles + taxonomy_titles + fallback,
            bucket="hiring_managers",
            context=context,
        )
    else:
        titles = ["Engineering Manager", "Software Engineering Manager", "Technical Lead", "Team Lead"]
    return list(dict.fromkeys(title for title in titles if title))


def _initial_manager_titles(context: JobContext | None) -> list[str]:
    context_manager_titles = _manager_context_search_titles(context)
    taxonomy_manager_titles = _occupation_manager_titles(
        context.occupation_keys if context else None,
        department=context.department if context else None,
    )
    fallback_titles = taxonomy_manager_titles or [
        "Engineering Manager",
        "Software Engineering Manager",
        "Software Development Manager",
        "Team Lead",
        "Technical Lead",
        "Director of Engineering",
        "Head of Engineering",
    ]
    if context:
        titles = _prioritize_titles_for_search(
            context_manager_titles + fallback_titles,
            bucket="hiring_managers",
            context=context,
        )
    else:
        titles = fallback_titles
    return list(dict.fromkeys(title for title in titles if title))


def _manager_geo_recovery_titles(context: JobContext | None) -> list[str]:
    base_titles = _initial_manager_titles(context)
    expanded = base_titles + [
        "Senior Engineering Manager",
        "Group Engineering Manager",
        "Director of Engineering",
        "Head of Engineering",
        "VP Engineering",
        "Engineering Leader",
    ]
    return list(dict.fromkeys(title for title in expanded if title))


def _manager_geo_recovery_keywords(context: JobContext | None) -> list[str]:
    keywords = ["engineering leader", "engineering leadership"]
    if context:
        keywords.extend(context.product_team_names[:1])
        keywords.extend(context.team_keywords[:2])
        keywords.extend(["engineering", "software"])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _recruiter_targeted_recovery_titles(context: JobContext | None) -> list[str]:
    base_titles = _companywide_recruiter_titles(context)
    expanded = base_titles + [
        "Talent Acquisition Manager",
        "Talent Acquisition Leader",
        "Senior Talent Acquisition Manager",
        "Head of Talent Acquisition",
        "University Recruitment",
    ]
    return list(dict.fromkeys(title for title in expanded if title))


def _recruiter_targeted_recovery_keywords(context: JobContext | None) -> list[str]:
    keywords = ["recruiter", "talent acquisition", "hiring"]
    if context and context.early_career:
        keywords.extend(["university recruitment", "campus recruiting", "early careers"])
    if context and context.department == "engineering":
        keywords.extend(["technical recruiting", "engineering hiring"])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _peer_targeted_recovery_titles(context: JobContext | None) -> list[str]:
    if not context:
        return _companywide_peer_titles(context)

    taxonomy_peers = _occupation_peer_titles(
        context.occupation_keys, department=context.department
    )
    if taxonomy_peers:
        titles = list(taxonomy_peers)
        if context.department == "engineering":
            if any(keyword in context.team_keywords for keyword in ("qa", "quality assurance", "test")):
                titles.extend([
                    "QA Engineer",
                    "Quality Assurance Engineer",
                    "Software Development Engineer in Test",
                ])
            if any(keyword in context.team_keywords for keyword in ("frontend", "ui", "web")):
                titles.extend(["Frontend Engineer", "UI Engineer"])
            if any(keyword in context.team_keywords for keyword in ("backend", "platform", "infrastructure")):
                titles.extend(["Backend Engineer", "Platform Engineer"])
        return list(dict.fromkeys(title for title in titles if title))

    return _companywide_peer_titles(context)


def _peer_targeted_recovery_keywords(context: JobContext | None) -> list[str]:
    keywords: list[str] = []
    if context:
        keywords.extend(context.team_keywords[:2])
        keywords.extend(context.product_team_names[:1])
        keywords.extend(_occupation_peer_titles(
            context.occupation_keys, department=context.department
        )[:2])
    if not keywords:
        keywords.extend(["employee", "team member"])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _manager_context_search_titles(context: JobContext | None) -> list[str]:
    if not context:
        return []
    filtered: list[str] = []
    for title in context.manager_titles:
        normalized = _normalize_identity(title)
        if not normalized:
            continue
        if not any(
            marker in normalized
            for marker in ("manager", "director", "head", "vice president", "vp")
        ):
            continue
        filtered.append(title)
    return list(dict.fromkeys(filtered))


def _sanitize_search_keywords(keywords: list[str], *, company_name: str) -> list[str]:
    sanitized: list[str] = []
    company_tokens = {
        _normalize_identity(company_name),
        _normalize_identity(company_name.replace("&", "and")),
    }
    for keyword in keywords:
        normalized = _normalize_identity(keyword)
        if not normalized or normalized in company_tokens:
            continue
        if normalized in {"company", "team", "role", "job"}:
            continue
        sanitized.append(keyword)
    return list(dict.fromkeys(sanitized))


def _companywide_peer_titles(context: JobContext | None, fallback_titles: list[str] | None = None) -> list[str]:
    if context:
        titles = _broaden_peer_titles_for_retry(context)
    else:
        titles = fallback_titles or ["Software Engineer", "Backend Engineer", "Platform Engineer", "Developer"]
    return list(dict.fromkeys(title for title in titles if title))


def _allow_director_plus(context: JobContext | None) -> bool:
    return bool(context and context.seniority in SENIOR_MANAGER_LEVELS)


def _manager_seniority_filters(context: JobContext | None) -> list[str]:
    if context and getattr(context, "early_career", False):
        return ["manager"]
    if context and context.seniority in {"intern", "junior"}:
        return ["manager"]
    return ["manager", "director", "vp"]


def _peer_seniority_filters(context: JobContext | None) -> list[str] | None:
    """Return Apollo seniority filters for peers, or None if no restriction.

    For early-career / junior roles, restrict peers to entry-level and
    mid-level so we don't surface Directors as "peers".
    For senior+ roles, allow broader range (no filter).
    """
    if not context:
        return None
    if context.early_career or context.seniority in {"intern", "junior"}:
        return ["entry", "junior", "mid"]
    if context.seniority in {"mid"}:
        return ["junior", "mid", "senior"]
    return None  # senior+ jobs: no restriction


def _is_ic_manager_title(text: str) -> bool:
    """Check if text contains an IC role with 'manager' in the title.

    Product Manager, Program Manager, etc. are individual-contributor roles
    even though they contain the word 'manager'.
    """
    return any(re.search(p, text) for p in _IC_MANAGER_PATTERNS)


_SENIOR_LEADERSHIP_PREFIXES = re.compile(
    r"\b(?:group|director|head|vp|vice president|chief|managing)\b",
    re.IGNORECASE,
)


def _recover_title_from_snippet(
    data: dict,
    *,
    company_name: str,
) -> tuple[str, int] | None:
    company_pattern = re.escape(company_name).replace(r"\ ", r"\s+")
    full_name = re.escape(data.get("full_name", "")).replace(r"\ ", r"\s+")
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    texts = [
        data.get("snippet", ""),
        data.get("title", ""),
        profile_data.get("linkedin_result_title", ""),
        profile_data.get("public_snippet", ""),
    ]
    public_url = _public_profile_url(data)
    is_theorg_public_url = "theorg.com" in (public_url or "")
    patterns = [
        rf"\b(?:currently serving as|serving as|works as|working as|is)\s+(?:an?\s+)?(?P<title>[^.;|,\n]+?)\s+(?:at|@)\s+{company_pattern}\b",
        rf"\b(?P<title>[^.;|,\n]+?)\s*@\s*{company_pattern}\b",
        rf"\b(?P<title>[^.;|,\n]+?)\s+at\s+{company_pattern}\b",
    ]

    for text in texts:
        normalized = " ".join((text or "").split())
        if not normalized:
            continue
        if not is_theorg_public_url and _is_recruiter_like(normalized):
            if re.search(
                rf"\babout\b.*\bi\s+(?:lead|manage)\b[^.;\n]{{0,80}}\b(?:talent acquisition|recruit(?:ing|ment))\b[^.;\n]{{0,80}}\b(?:at|for)\s+{company_pattern}\b",
                normalized,
                flags=re.IGNORECASE,
            ):
                if re.search(r"\b(canada|toronto|greater toronto area|gta)\b", normalized, flags=re.IGNORECASE):
                    return "Talent Acquisition Lead, Canada", 74
                return "Talent Acquisition Lead", 72
            if re.search(
                r"\babout\b.*\bresponsible for hiring\b[^.;\n]{0,80}\b(?:canada|toronto|greater toronto area|gta)\b",
                normalized,
                flags=re.IGNORECASE,
            ):
                return "Talent Acquisition Lead, Canada", 72
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            recovered = match.group("title").strip(" -,:|")
            if full_name:
                recovered = re.sub(rf"^{full_name}\s+(?:is|was)\s+", "", recovered, flags=re.IGNORECASE)
            recovered = re.sub(r"^(?:a|an)\s+", "", recovered, flags=re.IGNORECASE)
            recovered = recovered.strip(" -,:|")
            if recovered and not _title_is_weak(recovered, company_name) and _role_like_title(recovered):
                confidence = 75 if text == texts[0] else 65
                return recovered, confidence
        if not is_theorg_public_url and _is_recruiter_like(normalized):
            if re.search(r"\b(?:lead|head|manager|director)\b[^.;\n]{0,40}\b(?:talent acquisition|recruit)\b", normalized, flags=re.IGNORECASE):
                return "Talent Acquisition Leader", 60
            return "Talent Acquisition", 55
        if not is_theorg_public_url and _is_manager_like(normalized) and "engineering" in normalized:
            if "director" in normalized:
                return "Director of Engineering", 60
            return "Engineering Manager", 55
    return None
