"""Job-discovery constants: source lists, occupation routing, curated board registries."""

import logging
from app.services.occupation_taxonomy import discover_queries_for_occupations

logger = logging.getLogger(__name__)


DEFAULT_SEARCH_SOURCES = [
    "jsearch",
    "adzuna",
    "themuse",
    "remotive",
    "jobicy",
    "dice",
    "simplify",
    "newgrad",
]


STARTUP_BOARD_SOURCES = ["yc_jobs", "wellfound", "ventureloop"]


STARTUP_LINK_RESOLVE_CONCURRENCY = 6


# Hard per-source cap on a single aggregator fetch inside ``search_jobs``. Each
# source already fails soft, but a provider that hangs (slow scrape, upstream
# stall) would otherwise hold the whole ``asyncio.gather`` — and the interactive
# ``POST /api/jobs/search`` request — open indefinitely. Capping each source
# bounds the total request time to roughly this value; a source that exceeds it
# is dropped for that cycle (returns [] + a failed stat) instead of stalling
# every other source and the user's "Searching…" spinner.
SOURCE_FETCH_TIMEOUT_SECONDS = 30


# Source-health monitoring. Single transient fetch failures are logged at
# WARNING and never surface (a third-party board blipping for one cycle is
# expected). This catches the *sustained* case: a source failing across most of
# its attempts over a window, which the monitor task escalates to a single
# aggregated ERROR (→ one deduped Sentry issue per down source). A source must
# have at least MIN_ATTEMPTS runs in the window to be judged at all, so rarely
# run sources don't false-positive on a thin sample.
SOURCE_HEALTH_WINDOW_HOURS = 6
SOURCE_HEALTH_MIN_ATTEMPTS = 10
SOURCE_HEALTH_FAILURE_RATE = 0.9


DISCOVER_LIMIT_PER_SOURCE = 50


DISCOVER_LOCATION_FANOUT = 2


STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY = 3


APPLY_URL_REPAIR_MAX_JOBS = 20


# Occupations bound to non-tech industries: hospitals, schools, law firms,
# government, studios. For these, the curated tech ATS boards + tech-leaning
# boards (Dice, Simplify, newgrad) are pure noise, so discovery routes to the
# broad all-industry aggregators (JSearch / Adzuna / Remotive) instead.
INDUSTRY_BOUND_NONTECH_OCCUPATIONS = frozenset({
    "healthcare",
    "education_training",
    "legal_compliance",
    "public_sector_government",
    "arts_entertainment",
})


def _suppress_tech_sources(resolved_occupations: list[str] | None) -> bool:
    """True only when EVERY resolved occupation is industry-bound non-tech.

    Conservative: a cross-industry occupation (sales, marketing, finance, ...)
    keeps the tech sources, since those seekers may target tech companies. We
    only suppress when the whole search is for a sector where tech employers
    cannot be the answer (e.g. nursing, teaching, law).
    """
    occs = [o for o in (resolved_occupations or []) if o]
    if not occs:
        return False
    return all(o in INDUSTRY_BOUND_NONTECH_OCCUPATIONS for o in occs)


# The tech-only job boards (Dice / Jobicy / Remotive / Simplify) and the new-grad
# tech scraper only ever carry engineering/tech roles — Remotive even ignores the
# query and returns its own tech feed. Running them for a non-engineering discover
# (marketing, sales, finance, HR, ...) injects engineering roles that, when their
# titles don't classify, get mis-tagged with the discover occupation (a "Senior
# Quality Engineer" surfacing under Marketing). So gate them to the occupations
# they actually serve. The broad aggregators (JSearch/Adzuna/The Muse) and the
# curated non-tech vertical boards cover every other occupation.
ALL_INDUSTRY_DISCOVER_SOURCES = ["jsearch", "adzuna", "themuse"]
ENGINEERING_ONLY_DISCOVER_SOURCES = ["remotive", "jobicy", "dice", "simplify"]
ENGINEERING_RELEVANT_OCCUPATIONS = frozenset({
    "software_engineering",
    "data_engineer",
    "machine_learning_ai",
    "cybersecurity",
    "engineering_development",
    "data_analyst",
    "product_management",
})


def _engineering_relevant(resolved_occupations: list[str] | None) -> bool:
    """True when the engineering-only boards (and the tech new-grad scraper / ATS
    crawl) should run: the default feed (no occupations) and any search that
    includes an engineering-relevant occupation. A purely non-engineering search
    skips them so they can't inject tech noise."""
    occs = [o for o in (resolved_occupations or []) if o]
    if not occs:
        return True
    return any(o in ENGINEERING_RELEVANT_OCCUPATIONS for o in occs)


# Curated non-tech employer lists are the vertical analog of the tech ATS
# boards. This maps an occupation to the verticals whose employers actually hire
# it, so a nursing search pulls health systems and a finance search pulls banks.
#
# The big curated employers (health systems, universities, banks/insurers,
# retailers) are large organizations that staff a full back office — finance,
# HR, marketing, legal/compliance, project management, business analysis,
# management — not just their headline clinical/retail roles. So the
# general-professional occupations route to ALL_NONTECH_VERTICALS: a hospital
# posts accountants and HR partners the same way a bank posts nurses' payroll
# staff. Relevance is then handled downstream by occupation tagging + the feed's
# occupation filter + match scoring, exactly as it is for tech ATS boards (which
# also return every function, not just engineering). This is the routing breadth
# that closes the historical gap where marketing/HR/legal/PM/finance seekers got
# zero curated employers and collapsed onto the paid aggregators alone.
ALL_NONTECH_VERTICALS = frozenset({"healthcare", "education", "finance", "retail"})

OCCUPATION_VERTICALS: dict[str, frozenset[str]] = {
    # Industry-anchored: one obvious vertical home.
    "healthcare": frozenset({"healthcare"}),
    "education_training": frozenset({"education"}),
    "public_sector_government": frozenset({"government"}),
    # Back-office / general-professional functions every large employer staffs.
    "accounting_finance": ALL_NONTECH_VERTICALS,
    "human_resources": ALL_NONTECH_VERTICALS,
    "marketing": ALL_NONTECH_VERTICALS,
    "business_analyst": ALL_NONTECH_VERTICALS,
    "project_management": ALL_NONTECH_VERTICALS,
    "management_executive": ALL_NONTECH_VERTICALS,
    "legal_compliance": frozenset({"finance", "healthcare", "education"}),
    "consulting": frozenset({"finance", "retail"}),
    "product_management": frozenset({"finance", "retail"}),
    "creatives_design": frozenset({"retail", "education", "healthcare"}),
    # Cross-industry roles concentrated in specific verticals.
    "sales": frozenset({"finance", "retail"}),
    "customer_service_support": frozenset({"finance", "retail", "healthcare"}),
    "supply_chain": frozenset({"retail", "healthcare"}),
}


# Which provider serves each vertical. Most are Workday curated employers;
# federal government is served by USAJobs (the official federal board) instead,
# since agencies don't post on the curated Workday tenants.
WORKDAY_VERTICALS = frozenset({"healthcare", "education", "finance", "retail"})


GOVERNMENT_VERTICAL = "government"


def verticals_for_occupations(resolved_occupations: list[str] | None) -> set[str]:
    """Union of curated verticals the resolved occupations should pull from."""
    out: set[str] = set()
    for occ in resolved_occupations or []:
        out |= OCCUPATION_VERTICALS.get(occ, frozenset())
    return out


DEFAULT_SEED_SEARCHES = [
    {"query": "Software Engineer", "location": None, "remote_only": False},
    {"query": "New Grad Software", "location": None, "remote_only": False},
]


# Discovery queries spanning multiple roles. These are now derived from the
# occupation taxonomy at runtime via `discover_queries_for_occupations()`.
# DISCOVER_QUERIES remains as a backwards-compatible default fallback used
# when neither user occupations nor explicit queries are supplied.
DISCOVER_QUERIES: list[dict] = discover_queries_for_occupations(None)


# Curated ATS boards to pull from during discovery.
# These are popular tech companies with public Greenhouse/Ashby boards.
ATS_DISCOVER_BOARDS: list[dict[str, str]] = [
    # Greenhouse
    {"slug": "stripe", "ats": "greenhouse"},
    {"slug": "airbnb", "ats": "greenhouse"},
    {"slug": "figma", "ats": "greenhouse"},
    {"slug": "coinbase", "ats": "greenhouse"},
    {"slug": "robinhood", "ats": "greenhouse"},
    {"slug": "databricks", "ats": "greenhouse"},
    {"slug": "discord", "ats": "greenhouse"},
    {"slug": "brex", "ats": "greenhouse"},
    {"slug": "doordash", "ats": "greenhouse"},
    {"slug": "plaid", "ats": "greenhouse"},
    {"slug": "duolingo", "ats": "greenhouse"},
    {"slug": "squarespace", "ats": "greenhouse"},
    {"slug": "relativityspace", "ats": "greenhouse"},
    {"slug": "airtable", "ats": "greenhouse"},
    {"slug": "zscaler", "ats": "greenhouse"},
    {"slug": "instacart", "ats": "greenhouse"},
    {"slug": "scaleai", "ats": "greenhouse"},
    {"slug": "twitch", "ats": "greenhouse"},
    {"slug": "affirm", "ats": "greenhouse"},
    {"slug": "epicgames", "ats": "greenhouse"},
    {"slug": "roblox", "ats": "greenhouse"},
    {"slug": "postman", "ats": "greenhouse"},
    {"slug": "vercel", "ats": "greenhouse"},
    {"slug": "roku", "ats": "greenhouse"},
    {"slug": "gusto", "ats": "greenhouse"},
    {"slug": "jfrog", "ats": "greenhouse"},
    {"slug": "block", "ats": "greenhouse"},
    {"slug": "toast", "ats": "greenhouse"},
    {"slug": "spacex", "ats": "greenhouse"},
    {"slug": "marqeta", "ats": "greenhouse"},
    {"slug": "anthropic", "ats": "greenhouse"},
    {"slug": "asana", "ats": "greenhouse"},
    {"slug": "stabilityai", "ats": "greenhouse"},
    {"slug": "pinterest", "ats": "greenhouse"},
    {"slug": "togetherai", "ats": "greenhouse"},
    {"slug": "reddit", "ats": "greenhouse"},
    {"slug": "lucidmotors", "ats": "greenhouse"},
    {"slug": "dropbox", "ats": "greenhouse"},
    {"slug": "twilio", "ats": "greenhouse"},
    {"slug": "datadog", "ats": "greenhouse"},
    {"slug": "cloudflare", "ats": "greenhouse"},
    {"slug": "betterment", "ats": "greenhouse"},
    {"slug": "webflow", "ats": "greenhouse"},
    {"slug": "elastic", "ats": "greenhouse"},
    {"slug": "chime", "ats": "greenhouse"},
    {"slug": "flexport", "ats": "greenhouse"},
    {"slug": "billcom", "ats": "greenhouse"},
    {"slug": "gitlab", "ats": "greenhouse"},
    {"slug": "linkedin", "ats": "greenhouse"},
    {"slug": "mongodb", "ats": "greenhouse"},
    {"slug": "lyft", "ats": "greenhouse"},
    {"slug": "okta", "ats": "greenhouse"},
    {"slug": "waymo", "ats": "greenhouse"},
    {"slug": "andurilindustries", "ats": "greenhouse"},
    {"slug": "samsara", "ats": "greenhouse"},
    {"slug": "uberfreight", "ats": "greenhouse"},
    {"slug": "grammarly", "ats": "greenhouse"},
    {"slug": "verkada", "ats": "greenhouse"},
    {"slug": "niantic", "ats": "greenhouse"},
    {"slug": "nuro", "ats": "greenhouse"},
    {"slug": "canva", "ats": "greenhouse"},
    {"slug": "wiz", "ats": "greenhouse"},
    {"slug": "snyk", "ats": "greenhouse"},
    {"slug": "applovin", "ats": "greenhouse"},
    {"slug": "coreweave", "ats": "greenhouse"},
    # Ashby
    {"slug": "ramp", "ats": "ashby"},
    {"slug": "notion", "ats": "ashby"},
    {"slug": "openai", "ats": "ashby"},
    {"slug": "linear", "ats": "ashby"},
    {"slug": "cursor", "ats": "ashby"},
    {"slug": "snowflake", "ats": "ashby"},
    {"slug": "cohere", "ats": "ashby"},
    {"slug": "clickup", "ats": "ashby"},
    {"slug": "zapier", "ats": "ashby"},
    {"slug": "runway", "ats": "ashby"},
    {"slug": "deel", "ats": "ashby"},
    {"slug": "vanta", "ats": "ashby"},
    # Plaid runs its board on Greenhouse (see GREENHOUSE_DISCOVER_BOARDS); the
    # duplicate Ashby entry was removed to avoid double/stale imports (audit M5).
    {"slug": "elevenlabs", "ats": "ashby"},
    {"slug": "replit", "ats": "ashby"},
    {"slug": "perplexity", "ats": "ashby"},
    {"slug": "ashby", "ats": "ashby"},
    {"slug": "deepgram", "ats": "ashby"},
    {"slug": "confluent", "ats": "ashby"},
    {"slug": "benchling", "ats": "ashby"},
    {"slug": "supabase", "ats": "ashby"},
    {"slug": "sentry", "ats": "ashby"},
    {"slug": "sanity", "ats": "ashby"},
    {"slug": "modal", "ats": "ashby"},
    {"slug": "lambda", "ats": "ashby"},
    {"slug": "astronomer", "ats": "ashby"},
    {"slug": "drata", "ats": "ashby"},
    {"slug": "livekit", "ats": "ashby"},
    {"slug": "atlan", "ats": "ashby"},
    {"slug": "render", "ats": "ashby"},
    {"slug": "posthog", "ats": "ashby"},
    {"slug": "anyscale", "ats": "ashby"},
    {"slug": "neon", "ats": "ashby"},
    {"slug": "resend", "ats": "ashby"},
    {"slug": "railway", "ats": "ashby"},
    {"slug": "airbyte", "ats": "ashby"},
    # Canadian-HQ employers. The curated boards above skew US tech, which left
    # Canadian coverage thin (Canada was only reached when a US employer happened
    # to post a Canadian role). Each slug+ats below was verified live against the
    # ATS API and confirmed to carry real Canadian postings on 2026-06-22
    # (scripts/verify_canadian_ats_boards.py). Cohere is intentionally absent —
    # it is already listed above. A wrong slug silently returns nothing, so do
    # not add unverified employers here.
    {"slug": "lightspeedhq", "ats": "ashby"},  # Montréal
    {"slug": "neofinancial", "ats": "ashby"},  # Calgary
    {"slug": "hopper", "ats": "ashby"},  # Montréal
    {"slug": "1password", "ats": "ashby"},  # Toronto
    {"slug": "jobber", "ats": "ashby"},  # Edmonton
    {"slug": "wealthsimple", "ats": "ashby"},  # Toronto
    {"slug": "trulioo", "ats": "ashby"},  # Vancouver
    {"slug": "relayfi", "ats": "ashby"},  # Toronto
    {"slug": "benevity", "ats": "ashby"},  # Calgary
    {"slug": "float", "ats": "ashby"},  # Toronto
    {"slug": "koho", "ats": "ashby"},  # Toronto
    {"slug": "clearco", "ats": "ashby"},  # Toronto
    {"slug": "loopio", "ats": "ashby"},  # Toronto
    {"slug": "thinkific", "ats": "ashby"},  # Vancouver
    {"slug": "tenstorrent", "ats": "greenhouse"},  # Toronto
    {"slug": "mejuri", "ats": "greenhouse"},  # Toronto
    {"slug": "hootsuite", "ats": "greenhouse"},  # Vancouver
    {"slug": "later", "ats": "greenhouse"},  # Vancouver
    {"slug": "faire", "ats": "greenhouse"},  # Kitchener-Waterloo eng hub
]


# Lever companies (scraped from HTML since the API is deprecated)
LEVER_DISCOVER_SLUGS = [
    "spotify",
    "matchgroup",
    "palantir",
    "plaid",
    "ro",
    "outreach",
    "toptal",
    "jumpcloud",
    "greenlight",
    "wealthfront",
    "matillion",
    # Canadian-HQ employers on Lever, verified live on 2026-06-22
    # (scripts/verify_canadian_ats_boards.py).
    "waabi",  # Toronto — autonomous driving
    "knix",  # Toronto
    "waveapps",  # Toronto — Wave
    "wattpad",  # Toronto
]
