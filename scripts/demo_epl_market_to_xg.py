#!/usr/bin/env python3
"""Demo: REAL EPL market odds -> fair probabilities -> team xG (steps 2 -> 4).

The full chain on live-market data (unlike ``demo_market_to_xg.py``, which uses
hardcoded odds): The Odds API EPL slate -> parse per-book decimals ->
identity-match team names to FPL ids -> de-vig + consensus -> Poisson team xG.

Budget-safe by default: reads the cached snapshot in ``data/raw/the-odds-api/``
and spends ZERO credits. Pass ``--live`` to refresh through the (cache-first,
throttled) client — costs ``#markets x #regions`` credits, so only on a schedule.

    python scripts/demo_epl_market_to_xg.py            # offline, from cache
    python scripts/demo_epl_market_to_xg.py --live     # refresh (spends credits)
"""
from __future__ import annotations

import argparse
import json

from fpl_alpha.config import RAW
from fpl_alpha.identity import match_odds_name, teams_from_bootstrap
from fpl_alpha.ingestion import odds
from fpl_alpha.markets import consensus
from fpl_alpha.schemas import Team
from fpl_alpha.team_xg import fit_team_goals


def _load_odds(markets: str, regions: str, live: bool) -> list[dict]:
    if live:
        return odds.the_odds_api_epl(markets=markets, regions=regions, force=True)
    key = f"theoddsapi-epl-{markets.replace(',', '+')}-{regions.replace(',', '+')}"
    path = RAW / "the-odds-api" / f"{key}.json"
    if not path.exists():
        raise SystemExit(
            f"No cached odds at {path}.\n"
            f"Run once with --live (spends {len(markets.split(','))*len(regions.split(','))} "
            f"credits) or via scripts/snapshot_odds.py."
        )
    return json.loads(path.read_text())


def _load_teams() -> list[Team]:
    boot = RAW / "fpl" / "bootstrap-static.json"
    if not boot.exists():
        raise SystemExit(f"No cached FPL bootstrap at {boot}. Run scripts/refresh_fpl.py.")
    return teams_from_bootstrap(json.loads(boot.read_text()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markets", default="h2h,totals")
    ap.add_argument("--regions", default="uk")
    ap.add_argument("--live", action="store_true", help="refresh from API (spends credits)")
    args = ap.parse_args()

    teams = _load_teams()
    fixtures = odds.parse_the_odds_api_events(_load_odds(args.markets, args.regions, args.live))
    print(f"Loaded {len(fixtures)} EPL fixtures "
          f"({'LIVE' if args.live else 'cached'}, source=the-odds-api)\n")

    unresolved: list[str] = []
    for fo in fixtures:
        home = match_odds_name(fo.home_team, teams)
        away = match_odds_name(fo.away_team, teams)
        if home is None or away is None:  # log misses; never silently drop
            for name, m in ((fo.home_team, home), (fo.away_team, away)):
                if m is None:
                    unresolved.append(name)
            print(f"  SKIP {fo.home_team} vs {fo.away_team} — unresolved team name(s)")
            continue

        fixture_id = f"{home.short_name}_v_{away.short_name}"
        mps = consensus(fixture_id, "h2h", ["home", "draw", "away"], fo.h2h)
        if fo.totals:
            mps += consensus(fixture_id, f"totals_{fo.totals_line}", ["over", "under"], fo.totals)

        model = fit_team_goals(fixture_id, home.fpl_id, away.fpl_id, mps)
        exp_goals = model.lambda_home + model.lambda_away
        line = f", O/U {fo.totals_line}" if fo.totals_line else ""
        print(f"  {home.name} (H) vs {away.name} (A)   "
              f"[{len(fo.h2h)} h2h books, {len(fo.totals)} totals books{line}]")
        print(f"    xG: home {model.lambda_home:.2f}  away {model.lambda_away:.2f}  "
              f"(total {exp_goals:.2f})")
        print(f"    P(CS): home {model.p_clean_sheet_home:5.1%}  "
              f"away {model.p_clean_sheet_away:5.1%}")
        top = sorted(model.score_dist.items(), key=lambda kv: kv[1], reverse=True)[:3]
        print(f"    likeliest: " + "  ".join(f"{s} {p:4.1%}" for s, p in top) + "\n")

    if unresolved:
        print(f"Unresolved names ({len(unresolved)}): {sorted(set(unresolved))}")
        print("Add them to identity._EPL_TEAM_ALIASES.")


if __name__ == "__main__":
    main()
