"""Probe candidate Canadian-HQ employers across Greenhouse / Lever / Ashby.

For each candidate we try every (ats, slug) variant against the *same* live
endpoints the app uses, and report total postings + how many look Canadian.
Only boards that are live AND carry real Canadian roles should be added to
``constants.ATS_DISCOVER_BOARDS`` (an unverified slug silently returns nothing).

Run:  PYTHONPATH=backend python backend/scripts/verify_canadian_ats_boards.py
"""

import asyncio

import httpx

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

CA_TOKENS = (
    "canada", "toronto", "vancouver", "montreal", "montréal", "ottawa",
    "calgary", "waterloo", "kitchener", "edmonton", "winnipeg", "quebec",
    "québec", "ontario", "british columbia", "alberta", "mississauga",
    "halifax", "victoria, bc", ", on", ", bc", ", ab", ", qc", "remote - canada",
)

# name -> list of candidate slugs to try (probed against all 3 ATS).
CANDIDATES: dict[str, list[str]] = {
    "Shopify": ["shopify"],
    "Wealthsimple": ["wealthsimple"],
    "Cohere": ["cohere"],
    "1Password": ["1password", "agilebits"],
    "Clio": ["clio", "cliolegal"],
    "Hootsuite": ["hootsuite"],
    "Benevity": ["benevity"],
    "Vidyard": ["vidyard"],
    "Jobber": ["jobber", "getjobber"],
    "Ada": ["ada", "adasupport"],
    "Vena Solutions": ["venasolutions", "vena"],
    "PartnerStack": ["partnerstack"],
    "Float": ["float", "floatfinancial"],
    "Hopper": ["hopper"],
    "League": ["league"],
    "Wattpad": ["wattpad"],
    "Koho": ["koho", "kohofinancial"],
    "Neo Financial": ["neofinancial", "neo"],
    "Wave": ["wave", "waveapps", "wavehq"],
    "Thinkific": ["thinkific"],
    "Later": ["later", "latermedia"],
    "ApplyBoard": ["applyboard"],
    "Lightspeed": ["lightspeedhq", "lightspeed", "lightspeedcommerce"],
    "Coveo": ["coveo"],
    "Kinaxis": ["kinaxis"],
    "Dialogue": ["dialogue", "dialoguetech"],
    "Ecobee": ["ecobee"],
    "Clearco": ["clearco", "clearbanc"],
    "Trulioo": ["trulioo"],
    "Bench": ["benchaccounting", "bench"],
    "Symend": ["symend"],
    "Waabi": ["waabi"],
    "Properly": ["properly"],
    "Ritual": ["ritual"],
    "Nylas": ["nylas"],
    "Plooto": ["plooto"],
    "Helcim": ["helcim"],
    "Tenstorrent": ["tenstorrent"],
    "Faire": ["faire"],
    "Relay": ["relayfi", "relay"],
    "Borrowell": ["borrowell"],
    "FreshBooks": ["freshbooks"],
    "Sonder": ["sonder"],
    "Loopio": ["loopio"],
    "Mejuri": ["mejuri"],
    "Knix": ["knix"],
    "Snyk": ["snyk"],
    "Wealthfront": ["wealthfront"],  # control (US) — expect ~0 CA
}


def _count_ca(payload: object) -> int:
    """Crude Canadian-posting counter: stringify each job, match CA tokens."""
    jobs: list = []
    if isinstance(payload, dict):
        jobs = payload.get("jobs") or payload.get("data") or []
    elif isinstance(payload, list):
        jobs = payload
    ca = 0
    for job in jobs:
        blob = str(job).lower()
        if any(tok in blob for tok in CA_TOKENS):
            ca += 1
    return ca


def _total(payload: object) -> int:
    if isinstance(payload, dict):
        return len(payload.get("jobs") or payload.get("data") or [])
    if isinstance(payload, list):
        return len(payload)
    return 0


async def _probe(client: httpx.AsyncClient, ats: str, slug: str) -> tuple[int, int] | None:
    url = {"greenhouse": GREENHOUSE, "lever": LEVER, "ashby": ASHBY}[ats].format(slug=slug)
    try:
        r = await client.get(url, timeout=20.0)
        if r.status_code != 200:
            return None
        data = r.json()
        total = _total(data)
        if total == 0:
            return None
        return total, _count_ca(data)
    except Exception:
        return None


async def _probe_candidate(client, sem, name, slugs):
    async with sem:
        best = None
        for ats in ("greenhouse", "lever", "ashby"):
            for slug in slugs:
                res = await _probe(client, ats, slug)
                if res:
                    total, ca = res
                    if best is None or ca > best[3]:
                        best = (ats, slug, total, ca)
        return name, best


async def main() -> None:
    sem = asyncio.Semaphore(8)
    headers = {"User-Agent": "Mozilla/5.0 NexusReach-board-verify"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        results = await asyncio.gather(
            *[_probe_candidate(client, sem, n, s) for n, s in CANDIDATES.items()]
        )

    live = [(n, b) for n, b in results if b]
    dead = [n for n, b in results if not b]
    live.sort(key=lambda x: x[1][3], reverse=True)

    print(f"{'COMPANY':18} {'ATS':11} {'SLUG':22} {'TOTAL':>6} {'CA':>5}")
    print("-" * 66)
    for name, (ats, slug, total, ca) in live:
        flag = "  <- add" if ca > 0 else ""
        print(f"{name:18} {ats:11} {slug:22} {total:>6} {ca:>5}{flag}")

    print(f"\nLIVE with CA roles ({sum(1 for _, b in live if b[3] > 0)}):")
    add_lines = [
        f'    {{"slug": "{b[1]}", "ats": "{b[0]}"}},'
        for _, b in live if b[3] > 0
    ]
    print("\n".join(add_lines))
    print(f"\nNo live board found: {', '.join(dead) if dead else '(none)'}")


if __name__ == "__main__":
    asyncio.run(main())
