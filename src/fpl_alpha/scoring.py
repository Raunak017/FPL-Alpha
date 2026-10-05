"""Versioned Fantasy Premier League fixture scoring rules.

This module scores realised player events.  It intentionally does not estimate
probabilities: deterministic xPts assembly and simulation consume these rules
later, so the official constants live in one tested place.

Rules source: https://fantasy.premierleague.com/help/rules
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping, TypeAlias

Position: TypeAlias = str


@dataclass(frozen=True)
class FPLScoringRules:
    """Immutable official scoring rules for one FPL season/version."""

    version: str
    goal_points: Mapping[Position, int]
    clean_sheet_points: Mapping[Position, int]
    assist_points: int
    appearance_under_60_points: int
    appearance_60_plus_points: int
    saves_per_point: int
    save_points: int
    penalty_save_points: int
    penalty_miss_points: int
    own_goal_points: int
    yellow_card_points: int
    red_card_points: int
    goals_conceded_per_deduction: int
    goals_conceded_points: int
    defensive_contribution_points: int
    defender_defensive_contribution_threshold: int
    attacker_defensive_contribution_threshold: int
    max_bonus_points: int


FPL_2026_27: Final = FPLScoringRules(
    version="2026-27",
    goal_points=MappingProxyType({"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}),
    clean_sheet_points=MappingProxyType({"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}),
    assist_points=3,
    appearance_under_60_points=1,
    appearance_60_plus_points=2,
    saves_per_point=3,
    save_points=1,
    penalty_save_points=5,
    penalty_miss_points=-2,
    own_goal_points=-2,
    yellow_card_points=-1,
    red_card_points=-3,
    goals_conceded_per_deduction=2,
    goals_conceded_points=-1,
    defensive_contribution_points=2,
    defender_defensive_contribution_threshold=10,
    attacker_defensive_contribution_threshold=12,
    max_bonus_points=3,
)

RULESETS: Final = MappingProxyType({FPL_2026_27.version: FPL_2026_27})
CURRENT_RULESET: Final = FPL_2026_27


@dataclass(frozen=True)
class PlayerMatchEvents:
    """Official per-player fixture events required for deterministic scoring.

    ``clean_sheet`` must reflect whether the player earned a clean sheet, rather
    than merely whether their team kept one: a substituted player can retain it
    after the team later concedes.  ``goals_conceded`` is likewise the official
    player-specific count used for GKP/DEF deductions.
    """

    minutes: int
    goals: int = 0
    assists: int = 0
    clean_sheet: bool = False
    goals_conceded: int = 0
    saves: int = 0
    penalties_saved: int = 0
    penalties_missed: int = 0
    own_goals: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    clearances_blocks_interceptions: int = 0
    tackles: int = 0
    recoveries: int = 0
    bonus: int = 0


@dataclass(frozen=True)
class ScoreBreakdown:
    """Named FPL point components for one player fixture."""

    rules_version: str
    appearance_points: int
    goal_points: int
    assist_points: int
    clean_sheet_points: int
    save_points: int
    penalty_save_points: int
    defensive_contribution_points: int
    bonus_points: int
    goals_conceded_points: int
    penalty_miss_points: int
    own_goal_points: int
    card_points: int

    @property
    def total_points(self) -> int:
        """Total official FPL points for the fixture."""
        return sum(
            (
                self.appearance_points,
                self.goal_points,
                self.assist_points,
                self.clean_sheet_points,
                self.save_points,
                self.penalty_save_points,
                self.defensive_contribution_points,
                self.bonus_points,
                self.goals_conceded_points,
                self.penalty_miss_points,
                self.own_goal_points,
                self.card_points,
            )
        )


def rules_for(version: str) -> FPLScoringRules:
    """Return the registered ruleset for an exact FPL season/version."""
    try:
        return RULESETS[version]
    except KeyError as error:
        raise ValueError(f"unknown FPL scoring rules version: {version}") from error


def defensive_contribution_points(
    position: Position,
    clearances_blocks_interceptions: int,
    tackles: int,
    recoveries: int = 0,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> int:
    """Return the capped defensive-contribution award for one fixture."""
    _validate_position(position, rules)
    _validate_counts(
        clearances_blocks_interceptions=clearances_blocks_interceptions,
        tackles=tackles,
        recoveries=recoveries,
    )
    if position == "GKP":
        return 0
    contribution = clearances_blocks_interceptions + tackles
    threshold = rules.defender_defensive_contribution_threshold
    if position in {"MID", "FWD"}:
        contribution += recoveries
        threshold = rules.attacker_defensive_contribution_threshold
    return rules.defensive_contribution_points if contribution >= threshold else 0


def score_player_fixture(
    position: Position,
    events: PlayerMatchEvents,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> ScoreBreakdown:
    """Score one player's realised fixture events under a versioned ruleset."""
    _validate_position(position, rules)
    _validate_counts(
        minutes=events.minutes,
        goals=events.goals,
        assists=events.assists,
        goals_conceded=events.goals_conceded,
        saves=events.saves,
        penalties_saved=events.penalties_saved,
        penalties_missed=events.penalties_missed,
        own_goals=events.own_goals,
        yellow_cards=events.yellow_cards,
        red_cards=events.red_cards,
        clearances_blocks_interceptions=events.clearances_blocks_interceptions,
        tackles=events.tackles,
        recoveries=events.recoveries,
        bonus=events.bonus,
    )
    if events.bonus > rules.max_bonus_points:
        raise ValueError(f"bonus cannot exceed {rules.max_bonus_points}")

    appearance = 0
    if events.minutes >= 60:
        appearance = rules.appearance_60_plus_points
    elif events.minutes > 0:
        appearance = rules.appearance_under_60_points

    clean_sheet = (
        rules.clean_sheet_points[position]
        if events.clean_sheet and events.minutes >= 60
        else 0
    )
    saves = rules.save_points * (events.saves // rules.saves_per_point) if position == "GKP" else 0
    penalty_saves = rules.penalty_save_points * events.penalties_saved if position == "GKP" else 0
    conceded = (
        rules.goals_conceded_points
        * (events.goals_conceded // rules.goals_conceded_per_deduction)
        if position in {"GKP", "DEF"}
        else 0
    )

    # A red-card deduction includes any yellow-card deduction from that fixture.
    cards = rules.red_card_points * events.red_cards if events.red_cards else rules.yellow_card_points * events.yellow_cards
    return ScoreBreakdown(
        rules_version=rules.version,
        appearance_points=appearance,
        goal_points=rules.goal_points[position] * events.goals,
        assist_points=rules.assist_points * events.assists,
        clean_sheet_points=clean_sheet,
        save_points=saves,
        penalty_save_points=penalty_saves,
        defensive_contribution_points=defensive_contribution_points(
            position,
            events.clearances_blocks_interceptions,
            events.tackles,
            events.recoveries,
            rules=rules,
        ),
        bonus_points=events.bonus,
        goals_conceded_points=conceded,
        penalty_miss_points=rules.penalty_miss_points * events.penalties_missed,
        own_goal_points=rules.own_goal_points * events.own_goals,
        card_points=cards,
    )


def _validate_position(position: Position, rules: FPLScoringRules) -> None:
    if position not in rules.goal_points:
        raise ValueError(f"unknown FPL position: {position}")


def _validate_counts(**counts: int) -> None:
    for name, value in counts.items():
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
