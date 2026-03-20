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
    "ml": ["machine learning", " ml ", "deep learning", "ai", "artificial intelligence", "nlp", "computer vision"],
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

SENIORITY_PATTERNS: list[tuple[str, str]] = [
    (r"\bintern\b", "intern"),
    (r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b", "junior"),
    (r"\bmid[- ]?level\b|\bmid\b", "mid"),
    (r"\bsenior\b|\bsr\.?\b", "senior"),
    (r"\bstaff\b", "staff"),
    (r"\bprincipal\b", "principal"),
    (r"\blead\b|\btech lead\b|\bteam lead\b", "lead"),
    (r"\bmanager\b|\bengineering manager\b|\bem\b", "manager"),
    (r"\bdirector\b", "director"),
    (r"\bvp\b|\bvice president\b", "vp"),
    (r"\bc-level\b|\bcto\b|\bcio\b|\bciso\b", "executive"),
]


@dataclass
class JobContext:
    department: str
    team_keywords: list[str] = field(default_factory=list)
    domain_keywords: list[str] = field(default_factory=list)
    seniority: str = "mid"
    early_career: bool = False
    manager_titles: list[str] = field(default_factory=list)
    peer_titles: list[str] = field(default_factory=list)
    recruiter_titles: list[str] = field(default_factory=list)
    apollo_departments: list[str] = field(default_factory=list)


def _strip_html(text: str) -> str:
    return WHITESPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", text or "")).strip()


def _contains_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword.strip())}(?!\w)", text) is not None


EARLY_CAREER_PATTERNS = (
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
        if _contains_keyword(title_lower, keyword):
            scores[department] = scores.get(department, 0) + SECTION_WEIGHTS["title"]
        if _contains_keyword(lead_lower, keyword):
            scores[department] = scores.get(department, 0) + SECTION_WEIGHTS["lead"]
        if _contains_keyword(body_lower, keyword):
            scores[department] = scores.get(department, 0) + SECTION_WEIGHTS["body"]

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


def _detect_seniority(title_lower: str) -> str:
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, title_lower):
            return level
    return "mid"


def _extract_core_role(title: str) -> str:
    result = title.strip()
    for prefix in [
        r"(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|entry[- ]level|mid[- ]?level)\s+",
        r"\bii\b\s*[,|-]?\s*",
        r"\biii\b\s*[,|-]?\s*",
    ]:
        result = re.sub(prefix, "", result, count=1, flags=re.IGNORECASE)
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
    if core:
        titles.extend([
            f"{core} Manager",
            f"{core} Engineering Manager",
            f"{core} Team Lead",
            f"{core} Tech Lead",
        ])
        if seniority in {"staff", "principal", "manager", "director", "vp", "executive"}:
            titles.append(f"Head of {core}")

    dept_label = department.replace("_", " ").title()
    titles.extend([
        f"{dept_label} Manager",
        "Engineering Manager",
        "Team Lead",
        "Tech Lead",
    ])

    for keyword in keywords[:2]:
        label = _keyword_label(keyword)
        titles.extend([
            f"{label} Engineering Manager",
            f"{label} Lead",
        ])

    return list(dict.fromkeys(title for title in titles if title))


def _build_peer_titles(base_title: str, keywords: list[str], seniority: str) -> list[str]:
    titles: list[str] = []
    core = _extract_core_role(base_title)
    if core:
        titles.append(core)
        if "engineer" in core.lower():
            titles.append(core.replace("Engineer", "Developer"))
            titles.append(core.replace("Engineer", "Software Engineer"))
        elif "developer" in core.lower():
            titles.append(core.replace("Developer", "Engineer"))

    for keyword in keywords[:2]:
        label = _keyword_label(keyword)
        titles.extend([
            f"{label} Engineer",
            f"{label} Software Engineer",
        ])

    if seniority in {"senior", "staff", "lead", "principal"}:
        titles.extend([
            f"Senior {title}" for title in titles[:3] if title and not title.startswith("Senior ")
        ])

    return list(dict.fromkeys(title for title in titles if title))


def _build_recruiter_titles(
    department: str,
    domain_keywords: list[str],
    *,
    early_career: bool,
) -> list[str]:
    titles = ["Technical Recruiter", "Talent Acquisition", "Recruiter"]

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

    if early_career:
        titles.extend(
            [
                "Campus Recruiter",
                "University Recruiter",
                "Early Careers Recruiter",
                "University Programs Recruiter",
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

    seniority = _detect_seniority(title_lower)
    if early_career and seniority == "mid":
        seniority = "junior"
    apollo_departments = APOLLO_DEPARTMENT_SLUGS.get(department, ["engineering_technical"])
    manager_titles = _build_manager_titles(department, team_keywords, title, seniority)
    peer_titles = _build_peer_titles(title, team_keywords, seniority)
    recruiter_titles = _build_recruiter_titles(
        department,
        domain_keywords,
        early_career=early_career,
    )

    return JobContext(
        department=department,
        team_keywords=team_keywords,
        domain_keywords=domain_keywords,
        seniority=seniority,
        early_career=early_career,
        manager_titles=manager_titles,
        peer_titles=peer_titles,
        recruiter_titles=recruiter_titles,
        apollo_departments=apollo_departments,
    )
