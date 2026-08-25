"""Tests for the identity layer: normalization + odds-name matching."""
from fpl_alpha.identity import match_odds_name, players_from_bootstrap, teams_from_bootstrap
from fpl_alpha.schemas import Player, Team

# Minimal bootstrap-static fixture (only the fields the normalizers touch).
_BOOTSTRAP = {
    "teams": [
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"id": 13, "name": "Manchester City", "short_name": "MCI"},
    ],
    "elements": [
        {
            "id": 1,
            "web_name": "Ødegaard",
            "first_name": "Martin",
            "second_name": "Ødegaard",
            "team": 1,
            "element_type": 3,
            "now_cost": 85,
        },
        {
            "id": 2,
            "web_name": "Haaland",
            "first_name": "Erling",
            "second_name": "Haaland",
            "team": 13,
            "element_type": 4,
            "now_cost": 150,
        },
    ],
}


def test_players_from_bootstrap_normalizes_fields():
    players = players_from_bootstrap(_BOOTSTRAP)
    haaland = next(p for p in players if p.fpl_id == 2)
    assert haaland.position == "FWD"
    assert haaland.full_name == "Erling Haaland"
    assert haaland.team_fpl_id == 13


def test_teams_from_bootstrap():
    teams = teams_from_bootstrap(_BOOTSTRAP)
    assert {t.short_name for t in teams} == {"ARS", "MCI"}


def test_exact_match():
    teams = teams_from_bootstrap(_BOOTSTRAP)
    assert match_odds_name("Arsenal", teams).fpl_id == 1


def test_accent_insensitive_match():
    players = players_from_bootstrap(_BOOTSTRAP)
    assert match_odds_name("Odegaard", players).fpl_id == 1  # feed drops the Ø


def test_alias_match():
    city = Team(fpl_id=13, name="Manchester City", short_name="MCI", aliases=("Man City",))
    assert match_odds_name("Man City", [city]).fpl_id == 13


def test_fuzzy_match_within_threshold():
    players = players_from_bootstrap(_BOOTSTRAP)
    # Slight misspelling the odds feed might carry.
    assert match_odds_name("Haaland", players).fpl_id == 2


def test_returns_none_below_threshold():
    players = players_from_bootstrap(_BOOTSTRAP)
    assert match_odds_name("Lionel Messi", players) is None


def test_player_object_accepted_directly():
    p = Player(1, "Salah", "Mohamed Salah", 14, "MID", 130)
    assert match_odds_name("Mohamed Salah", [p]) is p
