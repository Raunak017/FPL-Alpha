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
import re
from typing import Any

from .schemas import Player, PlayerSnapshot, Team

_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Common provider forms for the FPL team labels. These are deliberately
# explicit: odds-event matching must not guess between similarly named teams.
_TEAM_ALIASES = {
    "brighton": ("Brighton and Hove Albion",),
    "man city": ("Manchester City",),
    "man utd": ("Manchester United", "Man United"),
    "newcastle": ("Newcastle United",),
    "nott m forest": ("Nottingham Forest",),
    "spurs": ("Tottenham", "Tottenham Hotspur"),
    "wolves": ("Wolverhampton Wanderers",),
}
_PROVIDER_TEAM_CODE = re.compile(r"\s*\([a-z]{2,4}\)\s*$", re.IGNORECASE)
_TRANSLITERATION = str.maketrans(
    {"ø": "o", "ł": "l", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe"}
)


def teams_from_bootstrap(bootstrap: dict[str, Any]) -> list[Team]:
    """Normalize bootstrap-static 'teams' into canonical Team records."""
    return [
        Team(
            fpl_id=t["id"],
            name=t["name"],
            short_name=t["short_name"],
            aliases=_TEAM_ALIASES.get(_norm(t["name"]), ()),
        )
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


def normalize_odds_name(s: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    'Ødegaard' -> 'odegaard', 'Man. City' -> 'man city'.
    """
    s = _PROVIDER_TEAM_CODE.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().translate(_TRANSLITERATION)
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    return " ".join(s.split())


_norm = normalize_odds_name


def _candidate_names(candidate: Player | Team) -> set[str]:
    """All normalized names a candidate can legitimately be called."""
    names: list[str] = list(candidate.aliases)
    if isinstance(candidate, Player):
        names += [candidate.web_name, candidate.full_name]
    else:  # Team
        names += [candidate.name, candidate.short_name]
        names += _TEAM_ALIASES.get(_norm(candidate.name), ())
    return {_norm(n) for n in names if n}


def match_odds_name_strict(
    name: str, candidates: Iterable[Player | Team]
) -> tuple[Player | Team, str] | None:
    """Resolve only one unambiguous normalized name; never fuzzy-guess.

    The normalizer accepts harmless provider formatting differences such as
    accents, punctuation, ``FC`` suffixes, and reversed first/last names.
    A non-unique or non-exact result stays unmatched.
    """
    target_variants = _name_variants(name)
    if not target_variants:
        return None

    exact_matches = [
        candidate
        for candidate in candidates
        if target_variants.intersection(
            variant for candidate_name in _candidate_names(candidate)
            for variant in _name_variants(candidate_name)
        )
    ]
    if len(exact_matches) == 1:
        return exact_matches[0], "normalized_exact"
    if exact_matches:
        return None

    target_tokens = set(_norm(name).split())
    if len(target_tokens) < 2:
        return None
    subset_matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Player)
        if len(set(_norm(candidate.full_name).split())) >= 2
        if (
            target_tokens.issubset(set(_norm(candidate.full_name).split()))
            or set(_norm(candidate.full_name).split()).issubset(target_tokens)
        )
    ]
    if len(subset_matches) == 1:
        return subset_matches[0], "full_name_token_subset"

    target_token_list = _norm(name).split()
    first_last_matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Player)
        if len(candidate_tokens := _norm(candidate.full_name).split()) >= 2
        if len(target_token_list) >= 2
        if (
            target_token_list[0] == candidate_tokens[0]
            and target_token_list[-1] == candidate_tokens[-1]
        )
    ]
    if len(first_last_matches) == 1:
        return first_last_matches[0], "first_last_exact"

    last_name_matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Player)
        if len(target_token_list) >= 2
        if target_token_list[-1] in set(_norm(candidate.full_name).split())
    ]
    return (last_name_matches[0], "unique_last_name") if len(last_name_matches) == 1 else None


def _name_variants(value: str) -> set[str]:
    normalized = _norm(value)
    if not normalized:
        return set()
    tokens = normalized.split()
    without_club_suffix = [token for token in tokens if token not in {"fc", "afc"}]
    variants = {normalized, " ".join(sorted(tokens))}
    if without_club_suffix:
        variants.update(
            {
                " ".join(without_club_suffix),
                " ".join(sorted(without_club_suffix)),
            }
        )
    return variants


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
