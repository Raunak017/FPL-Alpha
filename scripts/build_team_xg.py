#!/usr/bin/env python3
"""Build and store live market-implied team-goal projections from DuckDB."""
from __future__ import annotations

import argparse

from fpl_alpha.storage import open_database
from fpl_alpha.team_xg import build_and_persist_team_goal_projection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", action="append", type=int, required=True)
    parser.add_argument("--provider-key", default="propline")
    args = parser.parse_args()

    connection = open_database()
    try:
        connection.execute("BEGIN TRANSACTION")
        try:
            projections = [
                build_and_persist_team_goal_projection(
                    connection, fixture_id, args.provider_key
                )
                for fixture_id in args.fixture_id
            ]
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
    finally:
        connection.close()

    for projection in projections:
        model = projection.model
        print(f"Fixture {projection.fixture_fpl_id}:")
        print(
            f"  xG: home {model.lambda_home:.3f}, away {model.lambda_away:.3f}; "
            f"fit loss {projection.fit_loss:.6f}"
        )
        print(
            f"  clean sheets: home {model.p_clean_sheet_home:.4f}, "
            f"away {model.p_clean_sheet_away:.4f}"
        )
        print(
            "  source: "
            f"{projection.provider_key}/{', '.join(projection.provider_event_ids)} "
            f"({projection.source_captured_at_min.isoformat()} to "
            f"{projection.source_captured_at_max.isoformat()}, "
            f"{projection.source_market_snapshot_count} market snapshots)"
        )
        for comparison in projection.comparisons:
            print(
                f"  {comparison.market} {comparison.outcome}: "
                f"market {comparison.market_prob:.4f}, "
                f"model {comparison.model_prob:.4f} "
                f"({comparison.n_books} books)"
            )


if __name__ == "__main__":
    main()

