"""Job context extraction for targeted people discovery.

This utility keeps the contract intentionally small and deterministic:
- infer the strongest department signal
- keep only a few high-confidence technical/domain keywords
- derive recruiter, manager, and peer title variants from that context
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


SECTION_WEIGHTS = {
    "title": 6,
    "lead": 3,
    "body": 1,
}

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

DEPARTMENT_MAP: dict[str, str] = {
    "data scientist": "data_science",
    "data engineer": "data_science",
    "data analyst": "data_science",
    "machine learning": "data_science",
    "ml engineer": "data_science",
    "ai engineer": "data_science",
    "analytics": "data_science",
    "product manager": "product_management",
    "product owner": "product_management",
    "program manager": "product_management",
    "tpm": "product_management",
    "designer": "design",
    "ux": "design",
    "ui": "design",
    "marketing": "marketing",
    "sales": "sales",
    "account executive": "sales",
    "business development": "sales",
    "customer success": "customer_success",
    "customer support": "customer_success",
    "support engineer": "customer_success",
    "solutions engineer": "customer_success",
    "finance": "finance",
    "accounting": "finance",
    "financial analyst": "finance",
    "recruiter": "human_resources",
    "talent acquisition": "human_resources",
    "people operations": "human_resources",
    "human resources": "human_resources",
    "legal": "legal",
    "counsel": "legal",
    "compliance": "legal",
    "operations": "operations",
    "supply chain": "operations",
    "logistics": "operations",
    "security engineer": "information_technology",
    "cybersecurity": "information_technology",
    "infosec": "information_technology",
    "it ": "information_technology",
    "system admin": "information_technology",
    "network engineer": "information_technology",
    "engineer": "engineering",
    "developer": "engineering",
    "swe": "engineering",
    "sde": "engineering",
    "devops": "engineering",
    "sre": "engineering",
    "platform": "engineering",
    "infrastructure": "engineering",
    "architect": "engineering",
    "firmware": "engineering",
    "embedded": "engineering",
    "full stack": "engineering",
    "fullstack": "engineering",
    "qa": "engineering",
    "quality assurance": "engineering",
    "test engineer": "engineering",
    "sdet": "engineering",
}

APOLLO_DEPARTMENT_SLUGS: dict[str, list[str]] = {
    "engineering": ["engineering_technical"],
    "data_science": ["engineering_technical", "data"],
    "product_management": ["product_management"],
    "design": ["design"],
    "marketing": ["marketing"],
    "sales": ["sales"],
    "customer_success": ["support"],
    "finance": ["finance"],
    "human_resources": ["human_resources"],
    "legal": ["legal"],
    "operations": ["operations"],
    "information_technology": ["information_technology"],
}

TECHNICAL_KEYWORDS_MAP: dict[str, list[str]] = {
    "backend": ["backend", "back-end", "server-side", "api"],
    "frontend": ["frontend", "front-end", "client-side", "react", "angular", "vue"],
    "fullstack": ["full stack", "fullstack", "full-stack"],
    "mobile": ["mobile", "ios", "android", "react native", "flutter"],
    "devops": ["devops", "dev ops", "site reliability", "sre"],
    "platform": ["platform", "internal tools", "developer experience", "developer tools"],
    "ml": ["machine learning", " ml ", "deep learning", "nlp", "computer vision"],
    "llm": ["llm", "large language model", "rag", "retrieval augmented", "prompt engineering", "agentic", "fine-tuning", "fine tuning", "transformer", "generative ai", "gen ai"],
    "ai": ["ai", "artificial intelligence", "ai engineer", "ai engineering"],
    "data": ["data engineering", "data pipeline", "etl", "analytics", "data warehouse", "big data"],
    "security": ["security", "cybersecurity", "infosec", "appsec", "devsecops"],
    "cloud": ["cloud", "aws", "gcp", "azure", "kubernetes", "k8s"],
    "embedded": ["embedded", "firmware", "iot", "hardware"],
    "qa": ["qa", "quality assurance", "sdet"],
}

DOMAIN_KEYWORDS_MAP: dict[str, list[str]] = {
    "payments": ["payments", "billing", "checkout", "card", "fintech"],
    "marketplace": ["marketplace", "catalog", "discovery", "search", "merchant details"],
    "consumer": ["consumer", "direct to consumer", "customer experience"],
    "merchant": ["merchant", "merchant onboarding", "merchant success"],
    "credit": ["credit", "credit risk", "lending"],
    "risk": ["risk", "fraud", "underwriting", "risk platform"],
    "decisioning": ["decisioning", "decision engine", "eligibility", "approval"],
    "underwriting": ["underwriting", "adjudication"],
}

# Roles where "manager" in the title does NOT imply people-management seniority.
# These are IC roles that happen to contain the word "manager".
IC_MANAGER_ROLES = (
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

SENIORITY_PATTERNS: list[tuple[str, str]] = [
    (r"\bintern\b", "intern"),
    (r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b", "junior"),
    (r"\bmid[- ]?level\b|\bmid\b", "mid"),
    (r"\bsenior\b|\bsr\.?\b", "senior"),
    (r"\bstaff\b", "staff"),
    (r"\bprincipal\b", "principal"),
    (r"\blead\b|\btech lead\b|\bteam lead\b", "lead"),
    (r"\bengineering manager\b|\bem\b", "manager"),
    (r"\bdirector\b", "director"),
    (r"\bvp\b|\bvice president\b", "vp"),
    (r"\bc-level\b|\bcto\b|\bcio\b|\bciso\b", "executive"),
]


@dataclass
class JobContext:
    department: str
    team_keywords: list[str] = field(default_factory=list)
    domain_keywords: list[str] = field(default_factory=list)
    product_team_names: list[str] = field(default_factory=list)
    seniority: str = "mid"
    early_career: bool = False
    manager_titles: list[str] = field(default_factory=list)
    peer_titles: list[str] = field(default_factory=list)
    recruiter_titles: list[str] = field(default_factory=list)
    apollo_departments: list[str] = field(default_factory=list)
    job_locations: list[str] = field(default_factory=list)


def _strip_html(text: str) -> str:
    return WHITESPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", text or "")).strip()


def _contains_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword.strip())}(?!\w)", text) is not None


EARLY_CAREER_PATTERNS = (
    r"\bearly[- ]careers?\b",
    r"\bnew grad\b",
    r"\bgraduate\b",
    r"\bgraduat(?:e|ing)\b",
    r"\bcampus\b",
    r"\buniversity\b",
    r"\bco[- ]?op\b",
    r"\bstudent\b",
)

BOILERPLATE_SENTENCE_PATTERNS = (
    r"^about\s+[a-z0-9& .-]+$",
    r"^about us$",
    r"^about the company$",
    r"^why (?:join|work at)\b",
    r"^our mission\b",
    r"^our values\b",
    r"^benefits\b",
    r"^perks\b",
)

TITLE_QUALIFIER_PATTERNS = (
    r"\bearly[- ]careers?\b",
    r"\bnew grad(?:uate)?\b",
    r"\bcampus\b",
    r"\buniversity\b",
    r"\bco[- ]?op\b",
    r"\bintern(?:ship)?\b",
    r"\bstudent\b",
)

LOCATION_QUALIFIER_PATTERNS = (
    r"usa",
    r"us",
    r"canada",
    r"uk",
    r"emea",
    r"apac",
    r"remote",
    r"hybrid",
    r"onsite",
)


def _detect_early_career(title_lower: str, description_lower: str) -> bool:
    haystack = f"{title_lower} {description_lower}".strip()
    return any(re.search(pattern, haystack) for pattern in EARLY_CAREER_PATTERNS)


def _strip_boilerplate_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+|\s{2,}", text)
    kept: list[str] = []
    for sentence in sentences:
        normalized = sentence.strip().lower().strip(":.-")
        if not normalized:
            continue
        if any(re.search(pattern, normalized) for pattern in BOILERPLATE_SENTENCE_PATTERNS):
            continue
        kept.append(sentence.strip())
    return " ".join(kept)


def _extract_sections(title: str, description: str | None) -> tuple[str, str, str]:
    title_lower = title.lower().strip()
    desc_clean = _strip_html(description or "")
    desc_clean = _strip_boilerplate_sentences(desc_clean)
    desc_lower = desc_clean.lower()
    lead_lower = desc_lower[:1200]
    body_lower = desc_lower[1200:]
    return title_lower, lead_lower, body_lower


def _score_department(title_lower: str, lead_lower: str, body_lower: str) -> str:
    scores: dict[str, int] = {}
    for keyword, department in DEPARTMENT_MAP.items():
        # Give a specificity bonus for multi-word keywords.  "ai engineer"
        # (2 words) should outweigh "engineer" (1 word) when both match
        # in the same section, so more-specific department signals win.
        word_count = len(keyword.split())
        specificity_bonus = word_count - 1  # 0 for single-word, 1 for 2-word, etc.
        if _contains_keyword(title_lower, keyword):
            scores[department] = scores.get(department, 0) + SECTION_WEIGHTS["title"] + specificity_bonus
        if _contains_keyword(lead_lower, keyword):
            scores[department] = scores.get(department, 0) + SECTION_WEIGHTS["lead"] + specificity_bonus
        if _contains_keyword(body_lower, keyword):
            scores[department] = scores.get(department, 0) + SECTION_WEIGHTS["body"] + specificity_bonus

    if not scores:
        return "engineering"
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _score_keyword_group(
    keyword_map: dict[str, list[str]],
    title_lower: str,
    lead_lower: str,
    body_lower: str,
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for label, keywords in keyword_map.items():
        score = 0
        for keyword in keywords:
            if _contains_keyword(title_lower, keyword):
                score += SECTION_WEIGHTS["title"]
            if _contains_keyword(lead_lower, keyword):
                score += SECTION_WEIGHTS["lead"]
            if _contains_keyword(body_lower, keyword):
                score += SECTION_WEIGHTS["body"]
        if score:
            scores[label] = score
    return scores


def _top_keywords(scores: dict[str, int], *, min_score: int, limit: int) -> list[str]:
    ranked = [
        label
        for label, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score >= min_score
    ]
    return ranked[:limit]


def _is_ic_manager_role(title_lower: str) -> bool:
    """Return True if the title is an IC role that contains 'manager'."""
    return any(re.search(p, title_lower) for p in IC_MANAGER_ROLES)


def _detect_seniority(title_lower: str) -> str:
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, title_lower):
            # Bare "\bmanager\b" was removed from patterns, but if
            # the title says "Engineering Manager" it still matches.
            return level
    # If the title contains "manager" but it's an IC role (Product Manager,
    # Program Manager etc.), treat it as mid-level IC — not people-manager.
    if re.search(r"\bmanager\b", title_lower) and _is_ic_manager_role(title_lower):
        return "mid"
    # Genuine people-manager titles that weren't caught above
    if re.search(r"\bmanager\b", title_lower):
        return "manager"
    return "mid"


def _extract_core_role(title: str) -> str:
    result = title.strip()
    for prefix in [
        r"(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|entry[- ]level|mid[- ]?level)\s+",
        r"\bii\b\s*[,|-]?\s*",
        r"\biii\b\s*[,|-]?\s*",
    ]:
        result = re.sub(prefix, "", result, count=1, flags=re.IGNORECASE)
    title_qualifier_pattern = "|".join(TITLE_QUALIFIER_PATTERNS)
    location_qualifier_pattern = "|".join(LOCATION_QUALIFIER_PATTERNS)
    result = re.sub(
        rf"\s*[-,:|]\s*(?:{title_qualifier_pattern})\b.*$",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\s*\((?:{location_qualifier_pattern})\)\s*$",
        "",
        result,
        flags=re.IGNORECASE,
    )
    return WHITESPACE_RE.sub(" ", result).strip(" ,|-")


def _keyword_label(keyword: str) -> str:
    return keyword.replace("_", " ").title()


def _build_manager_titles(
    department: str,
    keywords: list[str],
    base_title: str,
    seniority: str,
) -> list[str]:
    titles: list[str] = []
    core = _extract_core_role(base_title)
    core_lower = core.lower()
    is_ic_mgr = _is_ic_manager_role(core_lower)

    # --- Product / Program / Project management (IC "manager" roles) ---
    if is_ic_mgr:
        # The hiring manager for a PM is a senior PM or product leader
        if "product manager" in core_lower:
            titles.extend([
                "Group Product Manager",
                "Senior Product Manager",
                "Director of Product",
                "Director of Product Management",
                "VP Product",
                "Head of Product",
                "Product Lead",
            ])
        elif "program manager" in core_lower:
            titles.extend([
                "Senior Program Manager",
                "Director of Program Management",
                "Head of Program Management",
                "Program Director",
            ])
        elif "project manager" in core_lower:
            titles.extend([
                "Senior Project Manager",
                "Director of Project Management",
                "Head of PMO",
                "Program Director",
            ])
        else:
            # Generic IC-manager role (account manager, etc.)
            role_family = re.sub(r"\bmanager\b", "", core_lower).strip()
            role_label = role_family.title() if role_family else ""
            if role_label:
                titles.extend([
                    f"Senior {core}",
                    f"Director of {role_label}",
                    f"Head of {role_label}",
                    f"VP {role_label}",
                ])

        # Team-specific product/program leaders
        for keyword in keywords[:2]:
            label = _keyword_label(keyword)
            titles.extend([
                f"{label} Product Lead",
                f"{label} Group Product Manager",
            ])

        return list(dict.fromkeys(title for title in titles if title))

    # --- Engineering / Technical roles ---
    if core:
        if "engineering manager" in core_lower:
            # Already a management title — manager's manager is a director/VP
            for keyword in keywords[:2]:
                label = _keyword_label(keyword)
                titles.append(f"{label} Engineering Director")
            titles.extend([
                "Senior Engineering Manager",
                "Director of Engineering",
                "VP Engineering",
                "Head of Engineering",
            ])
        elif "engineer" in core_lower or "engineering" in core_lower:
            engineering_core = re.sub(r"Engineer\b", "Engineering", core, flags=re.IGNORECASE)
            # Team-specific titles (highest precision at large orgs)
            for keyword in keywords[:2]:
                label = _keyword_label(keyword)
                titles.extend([
                    f"{label} Engineering Manager",
                    f"{label} Lead",
                    f"{label} Team Lead",
                ])
            titles.extend([
                f"{engineering_core} Manager",
                f"{engineering_core} Lead",
                f"{core} Team Lead",
                f"{core} Tech Lead",
            ])
        elif department == "design":
            for keyword in keywords[:2]:
                label = _keyword_label(keyword)
                titles.append(f"{label} Design Lead")
            titles.extend([
                f"Senior {core}",
                "Design Manager",
                "Head of Design",
                "Design Director",
                "UX Manager",
            ])
        elif department == "data_science":
            for keyword in keywords[:2]:
                label = _keyword_label(keyword)
                titles.append(f"{label} Data Science Lead")
            titles.extend([
                f"Senior {core}",
                "Data Science Manager",
                "Head of Data Science",
                "ML Engineering Manager",
                "Director of Data Science",
            ])
        else:
            for keyword in keywords[:2]:
                label = _keyword_label(keyword)
                titles.extend([
                    f"{label} Lead",
                    f"{label} Team Lead",
                ])
            titles.extend([
                f"{core} Lead",
                f"Senior {core}",
                f"{core} Team Lead",
            ])
        if seniority in {"staff", "principal", "manager", "director", "vp", "executive"}:
            titles.append(f"Head of {core}")

    dept_label = department.replace("_", " ").title()
    if department == "engineering":
        titles.extend([
            f"{dept_label} Manager",
            "Engineering Manager",
            "Team Lead",
            "Tech Lead",
        ])
    else:
        titles.append(f"{dept_label} Manager")

    return list(dict.fromkeys(title for title in titles if title))


def _build_peer_titles(
    base_title: str,
    keywords: list[str],
    seniority: str,
    department: str,
) -> list[str]:
    titles: list[str] = []
    core = _extract_core_role(base_title)
    core_lower = core.lower()
    is_ic_mgr = _is_ic_manager_role(core_lower)
    ml_like_role = (
        department == "data_science"
        and any(term in core_lower for term in ("machine learning", "ml", "ai", "applied scientist", "model training"))
    ) or ("data scientist" in core_lower) or ("model training" in core_lower)

    # --- Product / Program / Project manager peers ---
    if is_ic_mgr:
        titles.append(core)
        if "product manager" in core_lower:
            titles.extend([
                "Product Manager",
                "Associate Product Manager",
                "Technical Program Manager",
                "Product Analyst",
            ])
        elif "program manager" in core_lower:
            titles.extend([
                "Program Manager",
                "Technical Program Manager",
                "Project Manager",
            ])
        elif "project manager" in core_lower:
            titles.extend([
                "Project Manager",
                "Program Manager",
                "Project Coordinator",
            ])
        else:
            titles.append(core)

        # Seniority-adjacent variants
        if seniority in {"senior", "staff", "lead", "principal"}:
            titles.extend([
                f"Senior {title}" for title in titles[:3]
                if title and not title.startswith("Senior ")
            ])
        if seniority in {"junior", "mid", "intern"}:
            titles.extend([
                f"Associate {title}" for title in titles[:2]
                if title and not title.startswith("Associate ")
            ])
            # APM is very common shorthand
            if "product manager" in core_lower:
                titles.append("APM")

        # Team-specific peers
        for keyword in keywords[:2]:
            label = _keyword_label(keyword)
            titles.append(f"{label} Product Manager")

        return list(dict.fromkeys(title for title in titles if title))

    # --- Engineering / Technical peers ---
    if core:
        titles.append(core)
        if re.search(r"\bengineer\b", core_lower):
            titles.append(re.sub(r"\bEngineer\b", "Developer", core, flags=re.IGNORECASE))
            if "software engineer" not in core_lower:
                titles.append(re.sub(r"\bEngineer\b", "Software Engineer", core, flags=re.IGNORECASE))
        elif "developer" in core_lower:
            titles.append(core.replace("Developer", "Engineer"))
        elif "designer" in core_lower:
            # Design-specific peer expansion
            titles.extend([
                "UX Designer",
                "Product Designer",
                "UI Designer",
                "Visual Designer",
            ])
        elif "analyst" in core_lower:
            # Analyst-specific peer expansion
            titles.extend([
                "Data Analyst",
                "Business Analyst",
                "Analytics Engineer",
            ])
        if ml_like_role:
            titles.extend([
                "Machine Learning Engineer",
                "Software Engineer",
                "Applied Scientist",
                "Research Engineer",
                "Data Scientist",
                "Model Training Engineer",
                "Training Infrastructure Engineer",
            ])

    for keyword in keywords[:2]:
        if ml_like_role and keyword == "security":
            continue
        label = _keyword_label(keyword)
        titles.extend([
            f"{label} Engineer",
            f"{label} Software Engineer",
        ])

    # Seniority-adjacent variants for broader recall
    seniority_prefix_titles: list[str] = []
    if seniority in {"senior", "staff", "lead", "principal"}:
        seniority_prefix_titles.extend([
            f"Senior {title}" for title in titles[:3] if title and not title.startswith("Senior ")
        ])
    if seniority in {"junior", "mid", "intern"}:
        seniority_prefix_titles.extend([
            f"Junior {title}" for title in titles[:2] if title and not title.startswith("Junior ")
        ])
        seniority_prefix_titles.extend([
            f"Associate {title}" for title in titles[:2] if title and not title.startswith("Associate ")
        ])

    titles.extend(seniority_prefix_titles)

    # For broad engineering roles, add generic peer titles to improve recall
    if department == "engineering" and not ml_like_role:
        broad_peers = ["Software Engineer", "Software Developer"]
        for bp in broad_peers:
            if bp not in titles:
                titles.append(bp)

    # For early-career roles, add level-specific titles (e.g. "Software Engineer I",
    # "SWE I") that many large companies use for new-grad positions.  These are more
    # precise than generic "Software Engineer" and help surface same-cohort peers.
    if seniority in {"junior", "intern"} and department == "engineering":
        level_titles = [
            "Software Engineer I",
            "Software Engineer 1",
            "SWE I",
            "Junior Software Engineer",
            "New Grad Software Engineer",
        ]
        for lt in level_titles:
            if lt not in titles:
                titles.append(lt)

    return list(dict.fromkeys(title for title in titles if title))


def _build_recruiter_titles(
    department: str,
    domain_keywords: list[str],
    *,
    early_career: bool,
) -> list[str]:
    titles = [
        "Technical Recruiter",
        "Talent Acquisition",
        "Recruiter",
        "Talent Acquisition Partner",
    ]

    if department in {"engineering", "data_science"}:
        titles.insert(0, "Engineering Recruiter")
    elif department == "product_management":
        titles.append("Product Recruiter")
    elif department == "design":
        titles.append("Design Recruiter")
    else:
        titles.append(f"{department.replace('_', ' ').title()} Recruiter")

    if "credit" in domain_keywords or "risk" in domain_keywords or "decisioning" in domain_keywords:
        titles.append("Fintech Recruiter")

    # Talent Scout is used at companies like Uber, Meta, Google as a recruiter variant
    titles.append("Talent Scout")

    if early_career:
        titles.extend(
            [
                "Campus Recruiter",
                "University Recruiter",
                "Early Careers Recruiter",
                "University Programs Recruiter",
                "Early Talent Recruiter",
                "University Talent Scout",
                "Recruiting Coordinator",
                "University Programs",
                "Technical Sourcer",
            ]
        )

    return list(dict.fromkeys(titles))


def _keyword_labels_with_title_hits(
    keyword_map: dict[str, list[str]],
    title_lower: str,
) -> set[str]:
    labels: set[str] = set()
    for label, keywords in keyword_map.items():
        if any(_contains_keyword(title_lower, keyword) for keyword in keywords):
            labels.add(label)
    return labels


def _generic_early_career_engineering_title(title_lower: str, department: str, *, early_career: bool) -> bool:
    if not early_career or department != "engineering":
        return False
    if not any(term in title_lower for term in ("engineer", "developer", "swe", "sde")):
        return False
    technical_title_hits = _keyword_labels_with_title_hits(TECHNICAL_KEYWORDS_MAP, title_lower)
    domain_title_hits = _keyword_labels_with_title_hits(DOMAIN_KEYWORDS_MAP, title_lower)
    return not technical_title_hits and not domain_title_hits


def _conservative_early_career_keywords(
    scores: dict[str, int],
    *,
    title_hits: set[str],
    min_repeated_score: int,
    limit: int,
) -> list[str]:
    ranked: list[str] = []
    for label, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
        if label in title_hits or score >= min_repeated_score:
            ranked.append(label)
        if len(ranked) >= limit:
            break
    return ranked


# Common product/team/org name patterns to extract from job descriptions.
# These are capitalized multi-word phrases that indicate a specific product,
# platform, or team and are useful for scoping people searches.
_PRODUCT_NAME_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?: [A-Z][a-zA-Z0-9]+)+)\b"
)
# Phrases that look like product names but are actually generic.
_PRODUCT_NAME_STOPWORDS = frozenset({
    "About Us", "About The", "The Company", "The Team", "Our Team",
    "Our Mission", "We Are", "You Will", "What You", "Who You",
    "How You", "This Role", "The Role", "Your Role", "In This",
    "United States", "San Francisco", "New York", "Los Angeles",
    "Equal Opportunity", "Equal Employment", "Base Salary",
    "Job Description", "Key Responsibilities", "Nice To",
    "Must Have", "Years Of", "Bachelor Of",
    "North America", "Remote Work",
})


def _extract_title_product_name(title: str, company_name: str | None = None) -> str | None:
    """Extract a product/team name embedded in the job title after a separator.

    Many jobs use formats like:
    - "AI Engineer New Grad 2025-2026 - Poe"
    - "Software Engineer - Payments"
    - "ML Engineer - Search/Ranking, Poe"
    - "Senior Engineer - Uber Eats"

    Returns the trailing product name, or None if not found.
    """
    # Split on common separators: " - ", " — ", " | "
    for sep in (" - ", " — ", " | "):
        if sep in title:
            trailing = title.rsplit(sep, 1)[-1].strip()
            # Filter out generic suffixes that are not product names
            trailing_lower = trailing.lower()
            if trailing_lower in {
                "remote", "hybrid", "onsite", "on-site",
                "us", "usa", "uk", "canada", "emea", "apac",
                "full time", "full-time", "part time", "part-time",
                "contract", "internship",
            }:
                return None
            if company_name and trailing_lower == company_name.lower():
                return None
            # Must be a short-ish name (not a whole sentence)
            if len(trailing) <= 30 and trailing[0].isupper():
                return trailing
    return None


def _extract_product_team_names(
    description: str | None,
    company_name: str | None = None,
    title: str | None = None,
    limit: int = 3,
) -> list[str]:
    """Extract specific product/team/platform names from a job title and description.

    Sources:
    1. Title-embedded product name (text after " - " separator)
    2. Multi-word capitalized phrases appearing 2+ times in description
    3. Single-word capitalized names (3-20 chars) appearing 3+ times in
       description, as long as they are not common English words

    Examples: "Poe", "Data Cloud", "Einstein Analytics", "Commerce Cloud"
    """
    results: list[str] = []
    seen_lower: set[str] = set()

    # Source 1: Title-embedded product name (highest priority)
    if title:
        title_product = _extract_title_product_name(title, company_name)
        if title_product and title_product.lower() not in seen_lower:
            results.append(title_product)
            seen_lower.add(title_product.lower())

    if not description:
        return results[:limit]

    desc_clean = _strip_html(description)

    # Source 2: Multi-word capitalized phrases (existing logic)
    counts: dict[str, int] = {}
    for match in _PRODUCT_NAME_RE.finditer(desc_clean):
        name = match.group(1).strip()
        if len(name) < 4 or name in _PRODUCT_NAME_STOPWORDS:
            continue
        if company_name and name.lower() == company_name.lower():
            continue
        counts[name] = counts.get(name, 0) + 1

    frequent = [
        (name, count) for name, count in counts.items()
        if count >= 2
    ]
    frequent.sort(key=lambda x: (-x[1], len(x[0])))
    for name, _ in frequent:
        if name.lower() not in seen_lower:
            results.append(name)
            seen_lower.add(name.lower())

    # Source 3: Single-word capitalized names (e.g. "Poe", "Slack", "Figma")
    # Require 3+ mentions to filter noise, and skip common English words
    _SINGLE_WORD_STOPWORDS = {
        "the", "and", "for", "with", "our", "you", "your", "this",
        "that", "will", "are", "can", "from", "have", "has", "not",
        "all", "about", "team", "role", "work", "join", "help",
        "build", "experience", "skills", "ability", "knowledge",
        "strong", "years", "including", "working", "using",
        "engineering", "engineer", "software", "senior", "junior",
        "manager", "lead", "platform", "product", "data", "system",
        "service", "design", "development", "technical", "technology",
        "remote", "hybrid",
    }
    single_counts: dict[str, int] = {}
    for match in re.finditer(r"\b([A-Z][a-z]{2,19})\b", desc_clean):
        word = match.group(1)
        if word.lower() in _SINGLE_WORD_STOPWORDS:
            continue
        if company_name and word.lower() == company_name.lower():
            continue
        single_counts[word] = single_counts.get(word, 0) + 1

    single_frequent = [
        (name, count) for name, count in single_counts.items()
        if count >= 3
    ]
    single_frequent.sort(key=lambda x: (-x[1], len(x[0])))
    for name, _ in single_frequent:
        if name.lower() not in seen_lower:
            results.append(name)
            seen_lower.add(name.lower())

    return results[:limit]


def extract_job_context(title: str, description: str | None = None) -> JobContext:
    """Extract structured job context from a title and description."""
    title_lower, lead_lower, body_lower = _extract_sections(title, description)
    early_career = _detect_early_career(title_lower, f"{lead_lower} {body_lower}")

    department = _score_department(title_lower, lead_lower, body_lower)
    technical_scores = _score_keyword_group(TECHNICAL_KEYWORDS_MAP, title_lower, lead_lower, body_lower)
    domain_scores = _score_keyword_group(DOMAIN_KEYWORDS_MAP, title_lower, lead_lower, body_lower)

    technical_title_hits = _keyword_labels_with_title_hits(TECHNICAL_KEYWORDS_MAP, title_lower)
    domain_title_hits = _keyword_labels_with_title_hits(DOMAIN_KEYWORDS_MAP, title_lower)

    if _generic_early_career_engineering_title(title_lower, department, early_career=early_career):
        technical_keywords = _conservative_early_career_keywords(
            technical_scores,
            title_hits=technical_title_hits,
            min_repeated_score=8,
            limit=2,
        )
        domain_keywords = _conservative_early_career_keywords(
            domain_scores,
            title_hits=domain_title_hits,
            min_repeated_score=6,
            limit=2,
        )
    else:
        technical_keywords = _top_keywords(technical_scores, min_score=3, limit=2)
        domain_keywords = _top_keywords(domain_scores, min_score=2, limit=2)

    combined_scores = {
        **{keyword: technical_scores[keyword] for keyword in technical_keywords},
        **{keyword: domain_scores[keyword] for keyword in domain_keywords},
    }
    team_keywords = _top_keywords(combined_scores, min_score=2, limit=3)

    # For early-career roles, inject "new grad" as a team keyword so SERP-based
    # peer searches surface recent new-grad hires instead of long-tenured staff.
    if early_career and "new grad" not in team_keywords:
        team_keywords.append("new grad")

    seniority = _detect_seniority(title_lower)
    if early_career and seniority == "mid":
        seniority = "junior"
    apollo_departments = APOLLO_DEPARTMENT_SLUGS.get(department, ["engineering_technical"])
    manager_titles = _build_manager_titles(department, team_keywords, title, seniority)
    peer_titles = _build_peer_titles(title, team_keywords, seniority, department)
    recruiter_titles = _build_recruiter_titles(
        department,
        domain_keywords,
        early_career=early_career,
    )
    product_team_names = _extract_product_team_names(description, title=title)

    return JobContext(
        department=department,
        team_keywords=team_keywords,
        domain_keywords=domain_keywords,
        product_team_names=product_team_names,
        seniority=seniority,
        early_career=early_career,
        manager_titles=manager_titles,
        peer_titles=peer_titles,
        recruiter_titles=recruiter_titles,
        apollo_departments=apollo_departments,
    )
