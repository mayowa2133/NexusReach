"""Canonical goal keys offered by the waitlist signup form.

The form presents these as multi-select chips; the free-text detail reuses the
signup's ``note`` field. Keys are validated server-side so the stored ``goals``
array stays segmentable — an unknown key is dropped rather than persisted.

Keep in sync with ``GOAL_OPTIONS`` in ``frontend/src/components/WaitlistModal.tsx``.
"""

# key -> human label (the label lives in the frontend; kept here for reference
# and for the admin export to render something meaningful).
WAITLIST_GOALS: dict[str, str] = {
    "land_first_role": "Land my first role",
    "switch_companies": "Move to a better company",
    "career_change": "Change careers or industry",
    "internships": "Find internships",
    "reach_recruiters": "Reach recruiters directly",
    "warm_intros": "Get warm intros to people",
    "outreach_help": "Write better outreach",
}

WAITLIST_GOAL_KEYS: frozenset[str] = frozenset(WAITLIST_GOALS)

# Bound on how many chips a single signup may submit (there are only a handful).
MAX_WAITLIST_GOALS = 10


def clean_goals(goals: list[str] | None) -> list[str] | None:
    """Drop unknown/duplicate keys, preserving order. ``None`` when empty."""
    if not goals:
        return None
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in goals[:MAX_WAITLIST_GOALS]:
        key = (raw or "").strip()
        if key in WAITLIST_GOAL_KEYS and key not in seen:
            seen.add(key)
            cleaned.append(key)
    return cleaned or None
