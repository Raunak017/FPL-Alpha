#!/usr/bin/env python3
"""Demo: bookmaker odds -> fair probabilities -> team xG (Plan steps 3 -> 4).

Runs fully offline on hardcoded example odds for one fixture, so you can see the
whole step 3->4 chain without an odds API key. Swap in real de-vigged markets
once an odds feed is wired up.

    python scripts/demo_market_to_xg.py
"""
from fpl_alpha.markets import consensus
from fpl_alpha.team_xg import fit_team_goals

# --- Example fixture: a home favorite. Decimal odds from two imaginary books ---
FIXTURE = "MCI_v_BUR_2026-08-22"
HOME, AWAY = "Manchester City", "Burnley"

# 1X2 (home / draw / away) decimal odds per book, and Over/Under 2.5 totals.
H2H_BOOKS = [[1.30, 6.00, 9.00], [1.28, 6.20, 9.50]]
TOTALS_BOOKS = [[1.55, 2.45], [1.57, 2.40]]  # [over 2.5, under 2.5]


def main() -> None:
    # Step 3 — de-vig each market and build consensus fair probabilities.
    h2h = consensus(FIXTURE, "h2h", ["home", "draw", "away"], H2H_BOOKS)
    totals = consensus(FIXTURE, "totals_2.5", ["over", "under"], TOTALS_BOOKS)

    print(f"Fixture: {HOME} (H) vs {AWAY} (A)\n")
    print("Fair market probabilities (de-vigged, consensus of 2 books):")
    for mp in h2h + totals:
        print(f"  {mp.market:<12} {mp.outcome:<6} {mp.prob:6.1%}  (n={mp.n_books})")

    # Step 4 — fit Poisson team goal rates to those fair probabilities.
    model = fit_team_goals(FIXTURE, home_team_fpl_id=13, away_team_fpl_id=90,
                           market_probs=h2h + totals)

    print("\nMarket-implied team xG (independent Poisson):")
    print(f"  lambda_home ({HOME}): {model.lambda_home:.2f} expected goals")
    print(f"  lambda_away ({AWAY}): {model.lambda_away:.2f} expected goals")
    print(f"  P(clean sheet {HOME}): {model.p_clean_sheet_home:5.1%}")
    print(f"  P(clean sheet {AWAY}): {model.p_clean_sheet_away:5.1%}")

    top = sorted(model.score_dist.items(), key=lambda kv: kv[1], reverse=True)[:5]
    print("\n  Most likely scorelines (home-away):")
    for score, prob in top:
        print(f"    {score}   {prob:5.1%}")


if __name__ == "__main__":
    main()
