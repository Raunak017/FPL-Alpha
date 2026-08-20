"""Canonical identity layer: FPL is the source of truth for player/team IDs.

The hard problem here is joining odds-feed names ("Man City", "Erling Haaland")
to FPL element/team ids. Everything downstream keys off FPL ids, so this stage
owns the alias tables and the fuzzy matcher.

Matching is a cascade — exact/alias/normalized first, fuzzy (stdlib difflib) as
the fallback — with a threshold below which we return None rather than guess, so
misses stay visible instead of silently mapping to the wrong player.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher
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


def _norm(s: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    'Ødegaard' -> 'odegaard', 'Man. City' -> 'man city'.
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    return " ".join(s.split())


def _candidate_names(candidate: Player | Team) -> set[str]:
    """All normalized names a candidate can legitimately be called."""
    names: list[str] = list(candidate.aliases)
    if isinstance(candidate, Player):
        names += [candidate.web_name, candidate.full_name]
    else:  # Team
        names += [candidate.name, candidate.short_name]
    return {_norm(n) for n in names if n}


def match_odds_name(
    name: str,
    candidates: Iterable[Player | Team],
    *,
    threshold: float = 0.85,
) -> Player | Team | None:
    """Resolve a name from an odds feed to a canonical Player/Team.

    Returns the best match, or ``None`` if the best fuzzy score is below
    ``threshold`` — callers should log a None so unresolved names are visible
    rather than silently dropped.
    """
    target = _norm(name)
    if not target:
        return None

    best: Player | Team | None = None
    best_score = 0.0
    for candidate in candidates:
        for cand_name in _candidate_names(candidate):
            if cand_name == target:  # exact / alias / normalized hit
                return candidate
            score = SequenceMatcher(None, target, cand_name).ratio()
            if score > best_score:
                best_score, best = score, candidate

    return best if best_score >= threshold else None
