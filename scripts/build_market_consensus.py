#!/usr/bin/env python3
"""Print current fair match-market probabilities from DuckDB odds snapshots."""
from __future__ import annotations

import argparse

from fpl_alpha.markets import consensus_from_latest_odds
from fpl_alpha.storage import open_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", action="append", type=int, required=True)
    parser.add_argument("--provider", default="propline", help="Odds provider key (default: propline)")
    parser.add_argument(
        "--fit",
        action="store_true",
        help="Fit Poisson team goals and persist to DuckDB with provenance and residuals",
    )
    args = parser.parse_args()

    connection = open_database()
    try:
        for fixture_id in args.fixture_id:
            probabilities = consensus_from_latest_odds(
                connection, fixture_id, provider_key=args.provider
            )
            if not probabilities:
                print(f"Fixture {fixture_id}: no complete match-market books.")
                continue
            print(f"Fixture {fixture_id}:")
            for probability in probabilities:
                print(
                    f"  {probability.market} {probability.outcome}: "
                    f"{probability.prob:.4f} ({probability.n_books} books)"
                )

            if args.fit:
                from fpl_alpha.team_xg import fit_and_persist_fixture_team_xg

                record = fit_and_persist_fixture_team_xg(
                    connection, fixture_id, provider_key=args.provider
                )
                print(
                    f"  [Step 4 Fitted & Persisted] "
                    f"xG Home: {record.lambda_home:.2f}, xG Away: {record.lambda_away:.2f}, "
                    f"P(CS Home): {record.p_clean_sheet_home:.1%}, P(CS Away): {record.p_clean_sheet_away:.1%}, "
                    f"Loss: {record.fit_loss:.5f}"
                )
                print(f"  Residuals: {record.residuals}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
