"""Late ranking component for GitHub-team-confirmed contacts."""

from typing import Any


def github_team_rank(data: dict[str, Any]) -> int:
    """Favor contacts confirmed as the team that ships the code (0 wins).

    Applied after every safety axis, so it only reorders already-safe
    candidates - never blesses an unverified one.
    """
    return 0 if data.get("_github_team_member") else 1
