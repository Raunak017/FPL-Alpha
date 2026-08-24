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
from datetime import datetime
from typing import Any

from .schemas import Player, PlayerSnapshot, Team

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


def player_snapshots_from_bootstrap(
    bootstrap: dict[str, Any], captured_at: datetime
) -> list[PlayerSnapshot]:
    """Normalize bootstrap-static's time-varying player state.

    ``captured_at`` is supplied by the caller. For cached bootstrap data it is
    the local cache file write time, not an FPL-provided timestamp.
    """
    return [
        PlayerSnapshot(
            player_fpl_id=e["id"],
            captured_at=captured_at,
            now_cost=e["now_cost"],
            selected_by_percent=float(e["selected_by_percent"]),
            status=e["status"],
            total_points=e["total_points"],
            points_per_game=float(e["points_per_game"]),
            form=float(e["form"]),
            minutes=e["minutes"],
            starts=e["starts"],
            goals_scored=e["goals_scored"],
            assists=e["assists"],
            clean_sheets=e["clean_sheets"],
            bonus=e["bonus"],
            bps=e["bps"],
            expected_goals=float(e["expected_goals"]),
            expected_assists=float(e["expected_assists"]),
            expected_goal_involvements=float(e["expected_goal_involvements"]),
            expected_goals_conceded=float(e["expected_goals_conceded"]),
            clean_sheets_per_90=float(e["clean_sheets_per_90"]),
            defensive_contribution_per_90=float(e["defensive_contribution_per_90"]),
            expected_goals_per_90=float(e["expected_goals_per_90"]),
            expected_assists_per_90=float(e["expected_assists_per_90"]),
            expected_goal_involvements_per_90=float(e["expected_goal_involvements_per_90"]),
            expected_goals_conceded_per_90=float(e["expected_goals_conceded_per_90"]),
            goals_conceded_per_90=float(e["goals_conceded_per_90"]),
            saves_per_90=float(e["saves_per_90"]),
            starts_per_90=float(e["starts_per_90"]),
            influence=float(e["influence"]),
            creativity=float(e["creativity"]),
            threat=float(e["threat"]),
            ict_index=float(e["ict_index"]),
            chance_of_playing_next_round=e.get("chance_of_playing_next_round"),
            chance_of_playing_this_round=e.get("chance_of_playing_this_round"),
            transfers_in_event=e["transfers_in_event"],
            transfers_out_event=e["transfers_out_event"],
            transfers_in=e["transfers_in"],
            transfers_out=e["transfers_out"],
        )
        for e in bootstrap["elements"]
    ]


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
