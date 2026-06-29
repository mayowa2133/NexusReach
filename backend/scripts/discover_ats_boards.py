"""Auto-discover live Greenhouse / Lever / Ashby company boards at scale.

This is the "do what JobRight does" engine: the high-quality job supply comes from
crawling company ATS boards directly, and those boards are *auto-discoverable* —
a company's board slug is almost always a slugified version of its name. This
script takes a big seed of company names, probes each ATS for a live board,
verifies the match against the board's real company name (so a slug collision
can't sneak in a wrong company), and emits a registry the crawl can consume.

Output: ``app/data/discovered_ats_boards.json`` (committed). The crawl loads it via
``app/services/jobs/discovered_boards.py`` alongside the hand-curated constants.

Run:  cd backend && python scripts/discover_ats_boards.py
      cd backend && python scripts/discover_ats_boards.py --limit 200   # quick test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.jobs import constants  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "discovered_ats_boards.json"

# Curated, multi-industry seed of company NAMES. SimplifyJobs (pulled in below)
# covers tech; this list deliberately spans healthtech, fintech, edtech, media,
# consumer, biotech, climate, and logistics — the non-tech-adjacent industries
# that also live on Greenhouse/Lever/Ashby — so discovery isn't SWE-only.
SEED_COMPANIES: tuple[str, ...] = (
    # Healthtech / health systems on modern ATS
    "Oscar Health", "Cityblock Health", "Devoted Health", "Clover Health", "Headway",
    "Cedar", "Maven Clinic", "Ro", "Hims and Hers", "Carbon Health", "Forward",
    "Spring Health", "Lyra Health", "Komodo Health", "Tempus", "Flatiron Health",
    "Cohere Health", "Included Health", "Honor", "Papa", "Cricket Health", "Aledade",
    "Omada Health", "Hinge Health", "Sword Health", "Modern Health", "Alma", "Grow Therapy",
    "Color", "Function Health", "Garner Health", "Datavant",
    # Fintech
    "Rippling", "Ramp", "Mercury", "Brex", "Chime", "Dave", "MoneyLion", "Varo",
    "Affirm", "Klarna", "Nubank", "Plaid", "Marqeta", "Modern Treasury", "Unit",
    "Lithic", "Bond", "Pinwheel", "Method Financial", "Alloy", "Persona", "Sardine",
    "Petal", "Carta", "AngelList", "Public", "M1 Finance", "Wealthfront", "Betterment",
    "Stash", "Acorns", "Gusto", "Deel", "Remote", "Pilot", "Bench", "Settle", "Tipalti",
    # Edtech
    "Coursera", "Udemy", "Outschool", "Quizlet", "Newsela", "Course Hero", "Learneo",
    "Handshake", "Guild", "Degreed", "Multiverse", "Paper", "Amira Learning", "Ello",
    # Media / consumer / marketplace
    "Vimeo", "Patreon", "Substack", "Medium", "SoundCloud", "DraftKings", "FanDuel",
    "Hinge", "Bumble", "The Knot Worldwide", "Discord", "Reddit", "Pinterest", "Quora",
    "Whatnot", "StockX", "GOAT", "Grailed", "ThredUp", "Rent the Runway", "Warby Parker",
    "Glossier", "Away", "Allbirds", "Ritual", "Caraway", "Brooklinen", "Parachute",
    "Faire", "Mejuri", "Italic", "Thrasio", "Imperfect Foods", "Misfits Market",
    "Sweetgreen", "Cava", "Chipotle", "Toast", "Olo",
    # Climate / bio / industrial
    "Watershed", "Pachama", "Recursion", "Ginkgo Bioworks", "Benchling", "Mammoth Biosciences",
    "Form Energy", "Commonwealth Fusion Systems", "Redwood Materials", "Boom Supersonic",
    "Helion", "Twelve", "Crusoe", "Arcadia", "Aurora Solar", "Span",
    # Logistics / ops / dev-tools / AI
    "Flexport", "project44", "FourKites", "Flock Freight", "Stord",
    "Retool", "Airtable", "Webflow", "Amplitude", "Mixpanel", "Pendo", "Vercel",
    "Sourcegraph", "Replit", "Hugging Face", "Weights and Biases", "Scale AI",
    "Anthropic", "OpenAI", "Cohere", "Mistral AI", "Perplexity", "Glean", "Sierra",
    "Harvey", "Abridge", "Ambience Healthcare", "OpenEvidence",
    # Marketing-heavy consumer / media / martech / DTC (the brands that post the
    # most marketing + brand + comms roles and seasonal marketing internships).
    "HelloFresh", "Airbnb", "Roku", "Klaviyo", "Instacart", "The New York Times",
    "Reformation", "Spotify", "Hopper", "Twitch", "GetYourGuide", "Attentive",
    "Squarespace", "Iterable", "Vox Media", "Gymshark", "Harry's", "Olipop",
    "BuzzFeed", "Sprout Social", "Impossible Foods", "Rothy's", "Peloton",
    "Poshmark", "Bombas", "Yelp", "Mailchimp", "Lululemon", "Conde Nast",
    "SiriusXM", "Liquid Death", "Athletic Greens", "Curology", "Vuori", "Oatly",
    "Chobani", "Beyond Meat", "Gopuff", "Sephora",
)

_SUFFIX_WORDS = {
    "inc", "llc", "corp", "corporation", "co", "company", "group", "holdings",
    "labs", "technologies", "technology", "software", "systems", "solutions",
    "worldwide", "global", "the",
}

# A real single-employer board on Greenhouse/Lever/Ashby almost never exceeds a
# few hundred openings; way above this is a staffing agency / gig platform whose
# postings are client/gig roles, not the company's own — and they'd pollute the
# feed with mislabeled non-employer jobs. (Verified: "pulse" = an NHS staffing
# agency with 2.5k roles, "agency" = a freelance-AI-trainer gig platform.)
_MAX_PLAUSIBLE_BOARD_JOBS = 500

# Slugs too generic/aggregator-y to trust even when the name technically matches.
_GENERIC_SLUG_DENYLIST = frozenset({
    "pulse", "agency", "staffing", "recruiting", "recruitment", "talent",
    "careers", "career", "jobs", "job", "hiring", "hire", "remote", "freelance",
    "contractor", "contract", "gig", "people", "candidates", "apply", "employer",
    "workforce", "outsourcing", "consulting",
})


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _slug_candidates(name: str) -> list[str]:
    """Generate likely board slugs for a company name, most-likely first."""
    words = [w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w]
    core = [w for w in words if w not in _SUFFIX_WORDS] or words
    candidates = [
        "".join(words),          # cloverhealth
        "".join(core),           # cloverhealth (suffixes already gone)
        "-".join(core),          # clover-health  (Lever style)
        core[0] if core else "",  # clover
    ]
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and len(c) >= 2 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _name_matches(seed: str, board_name: str | None, slug: str) -> bool:
    """Guard against slug collisions: the board's real name must relate to the seed.

    Greenhouse/Ashby return the org name; Lever doesn't, so for Lever we require the
    slug to equal the seed's normalized form (a high-confidence exact match).
    """
    ns = _normalize(seed)
    if not board_name:  # Lever — no name in the API
        return _normalize(slug) == ns
    nb = _normalize(board_name)
    if not nb:
        return False
    if ns in nb or nb in ns:
        return True
    # token overlap on the significant first word (e.g. "Clover" ~ "Clover Health")
    seed_tokens = [w for w in re.split(r"[^a-z0-9]+", seed.lower()) if w and w not in _SUFFIX_WORDS]
    name_tokens = [w for w in re.split(r"[^a-z0-9]+", board_name.lower()) if w and w not in _SUFFIX_WORDS]
    return bool(seed_tokens and name_tokens and seed_tokens[0] == name_tokens[0])


async def _probe_greenhouse(client: httpx.AsyncClient, slug: str) -> tuple[str | None, int]:
    try:
        r = await client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            params={"content": "true"}, timeout=12,
        )
        if r.status_code == 200:
            d = r.json()
            return d.get("name"), len(d.get("jobs") or [])
    except Exception:
        pass
    return None, 0


async def _probe_lever(client: httpx.AsyncClient, slug: str) -> tuple[str | None, int]:
    try:
        r = await client.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=12)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return None, len(data)  # Lever has no org name
    except Exception:
        pass
    return None, 0


async def _probe_ashby(client: httpx.AsyncClient, slug: str) -> tuple[str | None, int]:
    try:
        r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=12)
        if r.status_code == 200:
            d = r.json()
            return d.get("organizationName"), len(d.get("jobs") or [])
    except Exception:
        pass
    return None, 0


_PROBERS = (("greenhouse", _probe_greenhouse), ("lever", _probe_lever), ("ashby", _probe_ashby))


async def discover_company(
    client: httpx.AsyncClient, name: str, sem: asyncio.Semaphore
) -> dict | None:
    """Return the best verified board for a company, or None."""
    async with sem:
        for slug in _slug_candidates(name):
            if slug in _GENERIC_SLUG_DENYLIST:
                continue
            for ats, probe in _PROBERS:
                board_name, n_jobs = await probe(client, slug)
                if not (0 < n_jobs <= _MAX_PLAUSIBLE_BOARD_JOBS):
                    continue  # no jobs, or aggregator-scale (likely staffing/gig)
                if _name_matches(name, board_name, slug):
                    return {
                        "company": name,
                        "ats": ats,
                        "slug": slug,
                        "jobs_seen": n_jobs,
                        "board_name": board_name or name,
                    }
    return None


def _existing_registry() -> set[tuple[str, str]]:
    existing = {(b["ats"], b["slug"]) for b in constants.ATS_DISCOVER_BOARDS}
    existing |= {("lever", s) for s in constants.LEVER_DISCOVER_SLUGS}
    return existing


async def _simplify_seed_companies() -> list[str]:
    """Company names currently hiring on the SimplifyJobs early-career lists."""
    try:
        from app.clients import remote_jobs_client  # noqa: PLC0415

        jobs = await remote_jobs_client.fetch_simplify_early_career_jobs(limit_per_repo=400)
    except Exception:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for j in jobs:
        c = (j.get("company_name") or "").strip()
        key = _normalize(c)
        if c and key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


async def _themuse_seed_companies(max_pages: int = 60) -> list[str]:
    """All-industry company names from The Muse public companies API (free, keyless).

    The Muse spans every industry, so this seeds the discovery with ~1k+ companies
    well beyond tech — exactly the breadth needed to grow non-tech board coverage.
    """
    base = "https://www.themuse.com/api/public/companies"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NexusReach/1.0)"}
    names: list[str] = []
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        try:
            first = await client.get(base, params={"page": 1})
            if first.status_code != 200:
                return []
            data = first.json()
        except Exception:
            return []
        names.extend(c["name"] for c in (data.get("results") or []) if c.get("name"))
        page_count = min(int(data.get("page_count") or 1), max_pages)

        async def fetch(page: int) -> list[str]:
            try:
                r = await client.get(base, params={"page": page})
                if r.status_code != 200:
                    return []
                return [c["name"] for c in (r.json().get("results") or []) if c.get("name")]
            except Exception:
                return []

        for batch in await asyncio.gather(*(fetch(p) for p in range(2, page_count + 1))):
            names.extend(batch)
    return names


async def _yc_seed_companies() -> list[str]:
    """Every YC company name (free yc-oss dataset). YC startups overwhelmingly run
    on Greenhouse/Lever/Ashby, so this is the highest-hit-rate seed by far."""
    url = "https://yc-oss.github.io/api/companies/all.json"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NexusReach/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=45, headers=headers) as client:
            r = await client.get(url, follow_redirects=True)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    companies = data if isinstance(data, list) else data.get("companies", [])
    return [c["name"] for c in companies if isinstance(c, dict) and c.get("name")]


async def main(limit: int | None) -> None:
    simplify, themuse, yc = await asyncio.gather(
        _simplify_seed_companies(), _themuse_seed_companies(), _yc_seed_companies()
    )
    print(f"Seed sources: curated={len(SEED_COMPANIES)} simplify={len(simplify)} "
          f"themuse={len(themuse)} yc={len(yc)}")
    # De-dupe by normalized name so "Audible, Inc." and "Audible" don't both probe.
    seen: set[str] = set()
    seed: list[str] = []
    for name in [*SEED_COMPANIES, *simplify, *themuse, *yc]:
        key = _normalize(name)
        if key and key not in seen:
            seen.add(key)
            seed.append(name)
    if limit:
        seed = seed[:limit]
    print(f"Seed companies (deduped): {len(seed)}")

    sem = asyncio.Semaphore(32)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(*(discover_company(client, n, sem) for n in seed))

    existing = _existing_registry()
    found = [r for r in results if r]
    new = [r for r in found if (r["ats"], r["slug"]) not in existing]
    # De-dupe discovered set itself by (ats, slug)
    deduped: dict[tuple[str, str], dict] = {}
    for r in sorted(new, key=lambda x: -x["jobs_seen"]):
        deduped.setdefault((r["ats"], r["slug"]), r)
    boards = sorted(deduped.values(), key=lambda x: -x["jobs_seen"])

    by_ats: dict[str, int] = {}
    for b in boards:
        by_ats[b["ats"]] = by_ats.get(b["ats"], 0) + 1
    total_jobs = sum(b["jobs_seen"] for b in boards)
    print(f"Live boards found: {len(found)} | NEW (not already in registry): {len(boards)}")
    print(f"  by ATS: {by_ats}")
    print(f"  total jobs discovered on new boards: {total_jobs}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(boards),
        "boards": [{"slug": b["slug"], "ats": b["ats"], "company": b["board_name"]} for b in boards],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {len(boards)} boards -> {OUTPUT_PATH}")
    print("Top 15 by job count:")
    for b in boards[:15]:
        print(f"  {b['ats']:11} {b['slug']:22} {b['jobs_seen']:>4} jobs  ({b['board_name']})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Cap seed size (quick test)")
    args = ap.parse_args()
    asyncio.run(main(args.limit))
