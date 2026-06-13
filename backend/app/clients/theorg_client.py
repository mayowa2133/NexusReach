"""Client helpers for fetching and parsing public The Org pages."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from app.clients import public_page_client
from app.utils.company_identity import extract_public_identity_hints

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    flags=re.DOTALL,
)
THEORG_HOSTS = {"theorg.com", "www.theorg.com"}


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return f"https://{host}{path}" if path else f"https://{host}"


def _extract_next_data(html: str) -> dict | None:
    if not html:
        return None
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _person_url(org_slug: str, person_slug: str | None) -> str:
    if not org_slug or not person_slug:
        return ""
    return f"https://theorg.com/org/{org_slug}/org-chart/{person_slug}"


def _team_url(org_slug: str, team_slug: str | None) -> str:
    if not org_slug or not team_slug:
        return ""
    return f"https://theorg.com/org/{org_slug}/teams/{team_slug}"


def _is_manager_like(title: str | None) -> bool:
    haystack = (title or "").lower()
    return any(keyword in haystack for keyword in ("manager", "director", "head", "vice president", "vp", "lead"))


def _light_position_to_person(
    raw: dict,
    *,
    company_name: str,
    org_slug: str,
    team_slug: str | None = None,
    team_name: str | None = None,
    origin_url: str | None = None,
    relationship: str = "team_member",
    parent_name: str | None = None,
    parent_title: str | None = None,
) -> dict | None:
    full_name = (raw.get("fullName") or raw.get("title") or "").strip()
    title = (raw.get("role") or raw.get("currentRole") or "").strip()
    person_slug = (raw.get("slug") or raw.get("positionSlug") or "").strip().lower()
    if not full_name or not title:
        return None

    public_url = _person_url(org_slug, person_slug) or (origin_url or "")
    page_type = "org_chart_person" if person_slug else "team"
    snippet_parts = [title]
    if team_name:
        snippet_parts.append(f"on the {team_name} team")
    snippet_parts.append(f"at {company_name}")

    return {
        "full_name": full_name,
        "title": title,
        "company": company_name,
        "department": team_name or "",
        "seniority": "",
        "linkedin_url": "",
        "apollo_id": "",
        "source": "theorg_traversal",
        "snippet": " ".join(snippet_parts),
        "profile_data": {
            "public_url": public_url,
            "public_host": "theorg.com",
            "public_identity_slug": org_slug,
            "public_page_type": page_type,
            "theorg_origin_url": origin_url or public_url,
            "theorg_team_slug": team_slug,
            "theorg_team_name": team_name,
            "theorg_relationship": relationship if relationship else ("manager" if _is_manager_like(title) else "team_member"),
            "theorg_parent_name": parent_name,
            "theorg_parent_title": parent_title,
        },
    }


async def fetch_page(url: str, *, timeout_seconds: int) -> dict | None:
    """Fetch a The Org page and parse embedded Next.js JSON."""
    normalized_url = _normalize_url(url)
    if urlparse(normalized_url).netloc.lower() not in THEORG_HOSTS:
        return None

    page = await public_page_client.fetch_page(
        normalized_url,
        timeout_seconds=timeout_seconds,
    )
    html = page.get("html") if page else ""
    markdown = page.get("markdown") if page else ""
    next_data = _extract_next_data(html or "")
    title = page.get("title") if page else ""

    if not next_data and (page or {}).get("retrieval_method") == "direct":
        rendered_page = await public_page_client.fetch_page(
            normalized_url,
            timeout_seconds=timeout_seconds,
            include_direct=False,
        )
        if rendered_page:
            page = rendered_page
            html = rendered_page.get("html") or html
            markdown = rendered_page.get("markdown") or markdown
            title = rendered_page.get("title") or title
            next_data = _extract_next_data(html or "")

    if not page and not next_data:
        return None

    hints = extract_public_identity_hints(normalized_url)
    return {
        "url": normalized_url,
        "title": title or "",
        "html": html,
        "markdown": markdown or "",
        "next_data": next_data,
        "retrieval_method": page.get("retrieval_method") if page else None,
        "fallback_used": page.get("fallback_used") if page else False,
        "public_identity_hints": hints,
    }


def parse_org_page(page: dict) -> dict | None:
    next_data = (page or {}).get("next_data") or {}
    page_props = next_data.get("props", {}).get("pageProps", {})
    initial_company = page_props.get("initialCompany") or {}
    initial_teams = page_props.get("initialTeams") or []
    initial_nodes = page_props.get("initialNodes") or []
    org_slug = (initial_company.get("slug") or (page.get("public_identity_hints") or {}).get("company_slug") or "").lower()
    html = (page or {}).get("html") or ""
    if not org_slug and html:
        m = re.search(r"/org/([a-z0-9-]+)", (page or {}).get("url") or "")
        if m:
            org_slug = m.group(1).lower()
    if not org_slug:
        return None

    teams = []
    for team in initial_teams:
        team_slug = (team.get("slug") or "").strip().lower()
        team_name = (team.get("name") or "").strip()
        if not team_slug or not team_name:
            continue
        teams.append(
            {
                "slug": team_slug,
                "name": team_name,
                "description": team.get("description") or "",
                "member_count": team.get("memberCount") or 0,
                "url": _team_url(org_slug, team_slug),
            }
        )

    leaders = []
    for node in initial_nodes:
        position = (((node.get("node") or {}).get("position")) or {})
        person = _light_position_to_person(
            {
                "fullName": position.get("fullName"),
                "role": position.get("role"),
                "slug": position.get("slug"),
            },
            company_name=initial_company.get("name") or "",
            org_slug=org_slug,
            origin_url=page.get("url"),
            relationship="manager",
        )
        if person:
            leaders.append(person)

    company_name = initial_company.get("name") or ""
    if not leaders and html:
        # Fallback: recover the leadership roster straight from the HTML.
        for entry in extract_org_roster(html):
            person = _light_position_to_person(
                entry,
                company_name=company_name,
                org_slug=org_slug,
                origin_url=page.get("url"),
                relationship="manager",
            )
            if person:
                person["profile_data"]["theorg_roster"] = True
                leaders.append(person)

    return {
        "org_slug": org_slug,
        "company_name": company_name,
        "org_url": page.get("url"),
        "teams": teams,
        "leaders": leaders,
        "html": html,
    }


def parse_team_page(page: dict) -> dict | None:
    next_data = (page or {}).get("next_data") or {}
    page_props = next_data.get("props", {}).get("pageProps", {})
    initial_team = page_props.get("initialTeam") or {}
    initial_company = page_props.get("initialCompany") or {}
    org_slug = (initial_company.get("slug") or (page.get("public_identity_hints") or {}).get("company_slug") or "").lower()
    team_slug = (initial_team.get("slug") or (page.get("public_identity_hints") or {}).get("team_slug") or "").lower()
    team_name = (initial_team.get("name") or "").strip()
    if not org_slug or not team_slug or not team_name:
        return None

    people = []
    for member in initial_team.get("members") or []:
        person = _light_position_to_person(
            member,
            company_name=initial_company.get("name") or "",
            org_slug=org_slug,
            team_slug=team_slug,
            team_name=team_name,
            origin_url=page.get("url"),
            relationship="manager" if _is_manager_like(member.get("role")) else "team_member",
        )
        if person:
            people.append(person)

    return {
        "org_slug": org_slug,
        "team_slug": team_slug,
        "team_name": team_name,
        "team_url": page.get("url"),
        "people": people,
    }


def parse_person_page(page: dict) -> dict | None:
    next_data = (page or {}).get("next_data") or {}
    page_props = next_data.get("props", {}).get("pageProps", {})
    initial_position = page_props.get("initialPosition") or {}
    company = initial_position.get("companyV2") or {}
    org_slug = (company.get("slug") or (page.get("public_identity_hints") or {}).get("company_slug") or "").lower()
    full_name = (initial_position.get("fullName") or "").strip()
    title = (initial_position.get("currentRole") or "").strip()
    if not org_slug or not full_name or not title:
        return None

    teams = initial_position.get("teams") or []
    primary_team = teams[0] if teams else {}
    team_slug = (primary_team.get("slug") or "").strip().lower() or None
    team_name = (primary_team.get("name") or "").strip() or None
    parent_name = full_name
    parent_title = title

    person = _light_position_to_person(
        {
            "fullName": full_name,
            "role": title,
            "slug": initial_position.get("slug"),
        },
        company_name=company.get("name") or "",
        org_slug=org_slug,
        team_slug=team_slug,
        team_name=team_name,
        origin_url=page.get("url"),
        relationship="manager" if _is_manager_like(title) else "team_member",
    )

    reports = []
    for report in initial_position.get("reports") or []:
        report_person = _light_position_to_person(
            report,
            company_name=company.get("name") or "",
            org_slug=org_slug,
            team_slug=team_slug,
            team_name=team_name,
            origin_url=page.get("url"),
            relationship="direct_report",
            parent_name=parent_name,
            parent_title=parent_title,
        )
        if report_person:
            reports.append(report_person)

    return {
        "org_slug": org_slug,
        "person": person,
        "reports": reports,
        "team_slug": team_slug,
        "team_name": team_name,
        "person_url": page.get("url"),
    }

# ---------------------------------------------------------------------------
# HTML-based extraction (current TheOrg pages embed people in JSON-LD +
# inline LightPosition objects rather than the legacy __NEXT_DATA__ initialNodes).
# ---------------------------------------------------------------------------

def _extract_json_array(html: str, key: str) -> list | None:
    """Bracket-match the JSON array assigned to "<key>": in raw HTML."""
    marker = f'"{key}":['
    idx = html.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker) - 1  # at the '['
    depth, i, in_str, esc = 0, start, False, False
    while i < len(html):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    break
        i += 1
    try:
        return json.loads(html[start:i + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def extract_org_roster(html: str) -> list[dict]:
    """Named leaders + titles from the Organization JSON-LD employee[] array.

    Returns dicts with name/title/slug. This is the org's notable people
    (C-level, VPs, heads) - the highest-value contacts for non-engineering
    roles where public-web x-ray surfaces only engineers.
    """
    employees = _extract_json_array(html, "employee") or []
    roster = []
    for emp in employees:
        if not isinstance(emp, dict) or emp.get("@type") != "Person":
            continue
        name = (emp.get("name") or "").strip()
        title = (emp.get("jobTitle") or "").strip()
        if not name or not title:
            continue
        slug = ""
        for ref in emp.get("sameAs") or []:
            if isinstance(ref, str) and "/org-chart/" in ref:
                slug = ref.rstrip("/").rsplit("/", 1)[-1]
                break
        roster.append({"fullName": name, "role": title, "slug": slug})
    return roster


_LIGHT_POSITION_RE = re.compile(
    r'"__typename":"LightPosition","id":(?P<id>\d+),"slug":"(?P<slug>[^"]*)",'
    r'"fullName":"(?P<name>[^"]{2,60})"(?P<mid>.*?)"role":"(?P<role>[^"]{2,80})"'
    r'(?:,"parentPositionId":(?P<parent>\d+|null))?',
    re.DOTALL,
)


def extract_positions(html: str) -> dict[int, dict]:
    """Map positionId -> {fullName, role, slug, parent} from LightPosition objects.

    This is TheOrg's org chart: each position carries the person, their role,
    and the parent position id, so a role's *direct manager* is resolvable.
    """
    positions: dict[int, dict] = {}
    for m in _LIGHT_POSITION_RE.finditer(html):
        try:
            pid = int(m.group("id"))
        except (TypeError, ValueError):
            continue
        parent = m.group("parent")
        positions[pid] = {
            "id": pid,
            "fullName": m.group("name").strip(),
            "role": m.group("role").strip(),
            "slug": (m.group("slug") or "").strip().lower(),
            "parent": int(parent) if parent and parent.isdigit() else None,
        }
    return positions


_MANAGER_ROLE_RE = re.compile(
    r"\b(manager|director|head|vp|vice president|chief|lead|principal|president)\b",
    re.IGNORECASE,
)


def resolve_reporting_managers(
    html: str,
    target_role: str,
    *,
    company_name: str,
    org_slug: str,
    origin_url: str | None = None,
    limit: int = 4,
) -> list[dict]:
    """Hiring-manager candidates for ``target_role`` from the org chart.

    Two strategies, best first:
      1. Parent-of-role: when a position matching the target role has its parent
         position rendered on the page, that parent is the literal manager.
      2. Same-function managers: manager-titled positions whose function group
         matches the target role's (e.g. a Sales req -> Commercial Sales Manager,
         Sales Director, CRO). Robust when the parent node is not loaded - which
         is common, since TheOrg lazy-loads only the visible subtree.
    """
    from app.services.people.occupation_gate import title_function_group

    positions = extract_positions(html)
    if not positions:
        return []
    target_group = title_function_group(target_role)
    target_tokens = {tok for tok in re.split(r"[^a-z0-9]+", target_role.lower()) if len(tok) > 2}

    managers: list[dict] = []
    seen: set[str] = set()

    def _add(pos: dict, *, reporting_line: bool) -> None:
        if not pos or pos["fullName"].lower() in seen:
            return
        person = _light_position_to_person(
            pos, company_name=company_name, org_slug=org_slug,
            origin_url=origin_url, relationship="manager",
        )
        if person:
            seen.add(pos["fullName"].lower())
            if reporting_line:
                person["profile_data"]["theorg_reporting_line"] = True
                person["_theorg_reporting_manager"] = True
            else:
                person["profile_data"]["theorg_function_leader"] = True
            managers.append(person)

    # 1) literal parent-of-role
    for pos in positions.values():
        role_tokens = {tok for tok in re.split(r"[^a-z0-9]+", pos["role"].lower()) if len(tok) > 2}
        if target_tokens and len(target_tokens & role_tokens) >= max(1, len(target_tokens) - 1):
            parent = positions.get(pos["parent"]) if pos["parent"] else None
            if parent and _MANAGER_ROLE_RE.search(parent["role"]):
                _add(parent, reporting_line=True)

    # 2) same-function managers (manager-titled, matching function group)
    if target_group is not None:
        for pos in positions.values():
            if len(managers) >= limit:
                break
            if not _MANAGER_ROLE_RE.search(pos["role"]):
                continue
            if title_function_group(pos["role"]) == target_group:
                _add(pos, reporting_line=False)

    return managers[:limit]
