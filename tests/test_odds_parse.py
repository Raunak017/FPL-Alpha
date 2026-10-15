"""Tests for The Odds API parser (ingestion -> FixtureOdds handoff)."""
from fpl_alpha.ingestion.odds import _modal_total_line, parse_the_odds_api_events


def _mkt(key, outcomes):
    return {"key": key, "outcomes": outcomes}


# One event, four books exercising the tricky cases:
#  - book A: h2h (outcomes out of order) + totals @ 2.5
#  - book B: h2h only
#  - book C: h2h + totals @ 2.5
#  - book D: totals @ 3.0 only (alternate line -> excluded from consensus)
_EVENT = {
    "id": "evt1",
    "commence_time": "2026-08-21T19:00:00Z",
    "home_team": "Arsenal",
    "away_team": "Coventry City",
    "bookmakers": [
        {"markets": [
            _mkt("h2h", [
                {"name": "Draw", "price": 7.5},
                {"name": "Coventry City", "price": 17.0},
                {"name": "Arsenal", "price": 1.18},
            ]),
            _mkt("totals", [
                {"name": "Over", "price": 1.9, "point": 2.5},
                {"name": "Under", "price": 1.9, "point": 2.5},
            ]),
        ]},
        {"markets": [
            _mkt("h2h", [
                {"name": "Arsenal", "price": 1.20},
                {"name": "Coventry City", "price": 16.0},
                {"name": "Draw", "price": 7.0},
            ]),
        ]},
        {"markets": [
            _mkt("h2h", [
                {"name": "Arsenal", "price": 1.19},
                {"name": "Coventry City", "price": 17.0},
                {"name": "Draw", "price": 7.2},
            ]),
            _mkt("totals", [
                {"name": "Over", "price": 1.95, "point": 2.5},
                {"name": "Under", "price": 1.85, "point": 2.5},
            ]),
        ]},
        {"markets": [
            _mkt("totals", [
                {"name": "Over", "price": 2.4, "point": 3.0},
                {"name": "Under", "price": 1.6, "point": 3.0},
            ]),
        ]},
    ],
}


def test_parse_basic_shape():
    (fo,) = parse_the_odds_api_events([_EVENT])
    assert fo.source == "the-odds-api"
    assert fo.event_id == "evt1"
    assert fo.home_team == "Arsenal" and fo.away_team == "Coventry City"


def test_h2h_rows_aligned_home_draw_away():
    (fo,) = parse_the_odds_api_events([_EVENT])
    # Three books quote a full h2h; each row is [home, draw, away] regardless
    # of the order the feed listed outcomes in.
    assert len(fo.h2h) == 3
    assert fo.h2h[0] == [1.18, 7.5, 17.0]


def test_totals_uses_modal_line_only():
    (fo,) = parse_the_odds_api_events([_EVENT])
    # Modal line is 2.5 (two books) not 3.0 (one book); only 2.5 rows kept.
    assert fo.totals_line == 2.5
    assert fo.totals == [[1.9, 1.9], [1.95, 1.85]]


def test_modal_line_tiebreak_prefers_lower():
    books = [
        {"markets": [_mkt("totals", [{"name": "Over", "price": 2, "point": 2.5},
                                      {"name": "Under", "price": 2, "point": 2.5}])]},
        {"markets": [_mkt("totals", [{"name": "Over", "price": 2, "point": 3.5},
                                     {"name": "Under", "price": 2, "point": 3.5}])]},
    ]
    assert _modal_total_line(books) == 2.5  # tie -> lower line


def test_no_totals_leaves_line_none():
    ev = {"id": "e", "commence_time": "", "home_team": "A", "away_team": "B",
          "bookmakers": [{"markets": [_mkt("h2h", [
              {"name": "A", "price": 2.0}, {"name": "Draw", "price": 3.0},
              {"name": "B", "price": 4.0}])]}]}
    (fo,) = parse_the_odds_api_events([ev])
    assert fo.totals == [] and fo.totals_line is None
    assert len(fo.h2h) == 1


def test_incomplete_h2h_row_skipped():
    # A book missing the draw price must not produce a half-populated row.
    ev = {"id": "e", "commence_time": "", "home_team": "A", "away_team": "B",
          "bookmakers": [{"markets": [_mkt("h2h", [
              {"name": "A", "price": 2.0}, {"name": "B", "price": 4.0}])]}]}
    (fo,) = parse_the_odds_api_events([ev])
    assert fo.h2h == []
