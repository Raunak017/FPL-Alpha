"""Canonical identity layer: FPL is the source of truth for player/team IDs.

The hard problem here is joining odds-feed names ("Man City", "Erling Haaland")
to FPL element/team ids. Everything downstream keys off FPL ids, so this stage
owns the alias tables and the fuzzy matcher.

Status: normalizers scaffolded; the odds<->FPL name matcher is the first real
task once an odds feed is flowing.
"""
from __future__ import annotations

from typing import Any

from .schemas import Player, Team

_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def teams_from_bootstrap(bootstrap: dict[str, Any]) -> list[Team]:
    """Normalize bootstrap-static 'teams' into canonical Team records."""
    return [
        Team(fpl_id=t["id"], name=t["name"], short_name=t["short_name"])
        for t in bootstrap["teams"]
    ]


def players_from_bootstrap(bootstrap: dict[str, Any]) -> list[Player]:
    """Normalize bootstrap-static 'elements' into canonical Player records."""
    out: list[Player] = []
    for e in bootstrap["elements"]:
        full = f"{e.get('first_name', '')} {e.get('second_name', '')}".strip()
        out.append(
            Player(
                fpl_id=e["id"],
                web_name=e["web_name"],
                full_name=full,
                team_fpl_id=e["team"],
                position=_POSITION.get(e["element_type"], "UNK"),
                now_cost=e["now_cost"],
            )
        )
    return out


def match_odds_name(name: str, candidates: list[Player | Team]) -> Player | Team | None:
    """Resolve a name from an odds feed to a canonical Player/Team.

    TODO(identity): exact -> alias-table -> normalized -> fuzzy (rapidfuzz)
    cascade, with an unresolved-names log so misses are visible, never silent.
    """
    raise NotImplementedError("odds<->FPL name matching not implemented yet")
