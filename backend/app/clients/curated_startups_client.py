"""Static curated startup list sourced from a hand-curated newsletter (April 2026).

Covers Series B, Series C, and Forbes 50 AI companies with known careers pages.
Pre-seed/seed/series A entries are omitted because the source did not include
usable careers URLs for them.

Skipped entries:
- External aggregator URLs (builtin.com listings)
- Homepage-only URLs with no careers path (worldlabs.ai/, ssi.inc/, etc.)
- Non-careers pages (inflection.ai/about)
- Duplicates across tiers (deduped by career_url)
"""

from __future__ import annotations

_CURATED_STARTUPS: list[dict] = [
    # --- Series B ---
    {"company_name": "Augment Code", "career_url": "https://augmentcode.com/careers", "series": "B"},
    {"company_name": "Cobot", "career_url": "https://co.bot/careers", "series": "B"},
    {"company_name": "Hume AI", "career_url": "https://hume.ai/careers", "series": "B"},
    {"company_name": "Taktile", "career_url": "https://taktile.com/careers", "series": "B"},
    {"company_name": "1X", "career_url": "https://1x.tech/careers", "series": "B"},
    {"company_name": "QuEra Computing", "career_url": "https://quera.com/careers", "series": "B"},
    {"company_name": "Concentric AI", "career_url": "https://concentric.ai/hiring", "series": "B"},
    {"company_name": "NEURA Robotics", "career_url": "https://jobs.neura-robotics.com", "series": "B"},
    {"company_name": "Granola", "career_url": "https://granola.ai/jobs", "series": "B"},
    {"company_name": "Protex AI", "career_url": "https://protex.ai/careers", "series": "B"},
    {"company_name": "Mytra", "career_url": "https://mytra.ai/careers", "series": "B"},
    {"company_name": "Norm AI", "career_url": "https://norm.ai/careers", "series": "B"},
    {"company_name": "Range", "career_url": "https://www.range.com/public/careers", "series": "B"},
    {"company_name": "Imbue", "career_url": "https://imbue.com/careers", "series": "B"},
    {"company_name": "Cynomi", "career_url": "https://cynomi.com/careers", "series": "B"},
    {"company_name": "Merlin Labs", "career_url": "https://careers.merlinlabs.com", "series": "B"},
    {"company_name": "Guidewheel", "career_url": "https://guidewheel.com/careers", "series": "B"},
    {"company_name": "Crisp", "career_url": "https://crisp.co/careers", "series": "B"},
    {"company_name": "Mercor", "career_url": "https://mercor.com/careers", "series": "B"},
    {"company_name": "Unstructured", "career_url": "https://unstructured.io/careers", "series": "B"},
    {"company_name": "CompScience", "career_url": "https://compscience.com/careers", "series": "B"},
    {"company_name": "Elisity", "career_url": "https://elisity.com/careers", "series": "B"},
    {"company_name": "Pika", "career_url": "https://pika.art/careers", "series": "B"},
    {"company_name": "Rogo", "career_url": "https://rogo.ai/careers", "series": "B"},
    {"company_name": "Assured", "career_url": "https://assured.com/careers", "series": "B"},
    {"company_name": "Pinwheel", "career_url": "https://pinwheelapi.com/company/careers", "series": "B"},
    {"company_name": "Bitwarden", "career_url": "https://bitwarden.com/careers", "series": "B"},
    {"company_name": "Armada", "career_url": "https://armada.ai/careers", "series": "B"},
    {"company_name": "Windfall", "career_url": "https://windfall.com/careers", "series": "B"},
    {"company_name": "Hi Marley", "career_url": "https://himarley.com/careers", "series": "B"},
    {"company_name": "Maxwell", "career_url": "https://himaxwell.com/company/careers", "series": "B"},
    {"company_name": "Lindus Health", "career_url": "https://lindushealth.com/careers", "series": "B"},
    {"company_name": "Vannevar Labs", "career_url": "https://vannevarlabs.com/careers", "series": "B"},
    {"company_name": "Honeycomb Insurance", "career_url": "https://honeycombinsurance.com/careers", "series": "B"},
    {"company_name": "Doppel", "career_url": "https://doppel.com/company/careers", "series": "B"},
    {"company_name": "Pryon", "career_url": "https://pryon.com/careers", "series": "B"},
    # --- Series C ---
    {"company_name": "Anysphere (Cursor)", "career_url": "https://cursor.com/careers", "series": "C"},
    {"company_name": "AssetWatch", "career_url": "https://assetwatch.com/careers", "series": "C"},
    {"company_name": "Celestial AI", "career_url": "https://celestial.ai/careers", "series": "C"},
    {"company_name": "Daisy", "career_url": "https://daisyintelligence.com/work-at-daisy", "series": "C"},
    {"company_name": "Laurel", "career_url": "https://laurel.ai/careers", "series": "C"},
    {"company_name": "Arine", "career_url": "https://arine.io/careers", "series": "C"},
    {"company_name": "Candid Health", "career_url": "https://candidhealth.com/careers", "series": "C"},
    {"company_name": "HawkAI", "career_url": "https://hawk.ai/about-hawk/careers", "series": "C"},
    {"company_name": "Metronome", "career_url": "https://metronome.com/company/careers", "series": "C"},
    {"company_name": "Peregrine", "career_url": "https://job-boards.greenhouse.io/peregrinetechnologies", "series": "C"},
    {"company_name": "Temporal Technologies", "career_url": "https://temporal.io/careers", "series": "C"},
    {"company_name": "fal", "career_url": "https://fal.ai/careers", "series": "C"},
    {"company_name": "Linear", "career_url": "https://linear.app/careers", "series": "C"},
    {"company_name": "Nirvana Insurance", "career_url": "https://nirvanatech.com/careers", "series": "C"},
    {"company_name": "True Anomaly", "career_url": "https://trueanomaly.space/careers", "series": "C"},
    {"company_name": "BuildOps", "career_url": "https://buildops.com/careers", "series": "C"},
    {"company_name": "Meter", "career_url": "https://meter.com/careers", "series": "C"},
    {"company_name": "Render", "career_url": "https://render.com/careers", "series": "C"},
    {"company_name": "Statsig", "career_url": "https://statsig.com/careers", "series": "C"},
    {"company_name": "Alpaca", "career_url": "https://alpaca.markets/hiring", "series": "C"},
    {"company_name": "AtoB", "career_url": "https://atob.com/careers", "series": "C"},
    {"company_name": "Canopy", "career_url": "https://getcanopy.com/careers", "series": "C"},
    {"company_name": "CHAOS Industries", "career_url": "https://job-boards.greenhouse.io/chaosindustries", "series": "C"},
    {"company_name": "ClickHouse", "career_url": "https://clickhouse.com/company/careers", "series": "C"},
    {"company_name": "Cohere Health", "career_url": "https://coherehealth.com/careers", "series": "C"},
    {"company_name": "Fora Travel", "career_url": "https://foratravel.com/careers", "series": "C"},
    {"company_name": "Gravitee", "career_url": "https://gravitee.io/careers", "series": "C"},
    {"company_name": "Hex", "career_url": "https://hex.tech/careers", "series": "C"},
    {"company_name": "Swimlane", "career_url": "https://swimlane.com/careers", "series": "C"},
    {"company_name": "Utilidata", "career_url": "https://utilidata.com/careers", "series": "C"},
    {"company_name": "Cast AI", "career_url": "https://cast.ai/careers", "series": "C"},
    {"company_name": "CloudZero", "career_url": "https://cloudzero.com/careers", "series": "C"},
    {"company_name": "Mercury", "career_url": "https://mercury.com/jobs", "series": "C"},
    {"company_name": "Novisto", "career_url": "https://novisto.com/careers", "series": "C"},
    {"company_name": "Arize AI", "career_url": "https://arize.com/careers", "series": "C"},
    {"company_name": "Baseten", "career_url": "https://baseten.co/careers", "series": "C"},
    # --- Forbes 50 AI (deduplicated against Series B/C above) ---
    {"company_name": "Legora", "career_url": "https://legora.com/careers", "series": "forbes_ai"},
    {"company_name": "Reflection AI", "career_url": "https://reflection.ai/careers", "series": "forbes_ai"},
    {"company_name": "Physical Intelligence", "career_url": "https://www.pi.website/join-us", "series": "forbes_ai"},
    {"company_name": "Speak", "career_url": "https://www.speak.com/careers", "series": "forbes_ai"},
    {"company_name": "Chai Discovery", "career_url": "https://www.chaidiscovery.com/careers", "series": "forbes_ai"},
    {"company_name": "Black Forest Labs", "career_url": "https://bfl.ai/careers", "series": "forbes_ai"},
    {"company_name": "Skild AI", "career_url": "https://www.skild.ai/careers", "series": "forbes_ai"},
    {"company_name": "Sierra", "career_url": "https://sierra.ai/careers", "series": "forbes_ai"},
    {"company_name": "Mistral AI", "career_url": "https://mistral.ai/careers", "series": "forbes_ai"},
    {"company_name": "Lovable", "career_url": "https://lovable.dev/careers", "series": "forbes_ai"},
    {"company_name": "Listen Labs", "career_url": "https://www.listenlabs.ai/careers", "series": "forbes_ai"},
    {"company_name": "Genspark", "career_url": "https://www.genspark.ai/careers", "series": "forbes_ai"},
    {"company_name": "Decagon", "career_url": "https://decagon.ai/careers", "series": "forbes_ai"},
    {"company_name": "Together AI", "career_url": "https://www.together.ai/careers", "series": "forbes_ai"},
    {"company_name": "Suno", "career_url": "https://suno.com/careers", "series": "forbes_ai"},
    {"company_name": "Perplexity", "career_url": "https://www.perplexity.ai/careers", "series": "forbes_ai"},
    {"company_name": "OpenEvidence", "career_url": "https://www.openevidence.com/careers", "series": "forbes_ai"},
    {"company_name": "krea.ai", "career_url": "https://www.krea.ai/careers", "series": "forbes_ai"},
    {"company_name": "HeyGen", "career_url": "https://www.heygen.com/careers", "series": "forbes_ai"},
    {"company_name": "Harvey", "career_url": "https://www.harvey.ai/careers", "series": "forbes_ai"},
    {"company_name": "Fireworks AI", "career_url": "https://fireworks.ai/careers", "series": "forbes_ai"},
    {"company_name": "ElevenLabs", "career_url": "https://elevenlabs.io/careers", "series": "forbes_ai"},
    {"company_name": "Midjourney", "career_url": "https://www.midjourney.com/careers", "series": "forbes_ai"},
    {"company_name": "Cyera", "career_url": "https://www.cyera.com/careers", "series": "forbes_ai"},
    {"company_name": "Notion", "career_url": "https://www.notion.so/careers", "series": "forbes_ai"},
    {"company_name": "Surge AI", "career_url": "https://surgehq.ai/careers", "series": "forbes_ai"},
    {"company_name": "Gamma", "career_url": "https://gamma.app/careers", "series": "forbes_ai"},
    {"company_name": "Glean", "career_url": "https://www.glean.com/careers", "series": "forbes_ai"},
    {"company_name": "Cohere", "career_url": "https://cohere.com/careers", "series": "forbes_ai"},
    {"company_name": "Runway", "career_url": "https://runwayml.com/careers", "series": "forbes_ai"},
    {"company_name": "Crusoe", "career_url": "https://www.crusoe.ai/about/careers", "series": "forbes_ai"},
    {"company_name": "Abridge", "career_url": "https://jobs.ashbyhq.com/abridge", "series": "forbes_ai"},
    {"company_name": "Synthesia", "career_url": "https://www.synthesia.io/careers", "series": "forbes_ai"},
    {"company_name": "SambaNova", "career_url": "https://sambanova.ai/careers", "series": "forbes_ai"},
    {"company_name": "EliseAI", "career_url": "https://www.eliseai.com/careers", "series": "forbes_ai"},
    {"company_name": "Clay", "career_url": "https://www.clay.com/careers", "series": "forbes_ai"},
    {"company_name": "Applied Intuition", "career_url": "https://www.appliedintuition.com/careers", "series": "forbes_ai"},
    {"company_name": "Cognition", "career_url": "https://cognition.ai/careers", "series": "forbes_ai"},
    {"company_name": "Replit", "career_url": "https://replit.com/careers", "series": "forbes_ai"},
    {"company_name": "OpenAI", "career_url": "https://openai.com/careers", "series": "forbes_ai"},
    {"company_name": "Anthropic", "career_url": "https://www.anthropic.com/careers", "series": "forbes_ai"},
    {"company_name": "Databricks", "career_url": "https://www.databricks.com/company/careers", "series": "forbes_ai"},
]


def get_curated_startups() -> list[dict]:
    """Return the full curated startup list.

    Each entry has: company_name (str), career_url (str), series (str).
    The list is already deduplicated by career_url across tiers.
    """
    return list(_CURATED_STARTUPS)
