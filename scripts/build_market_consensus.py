#!/usr/bin/env python3
"""Print current fair match-market probabilities from DuckDB odds snapshots."""
from __future__ import annotations

import argparse

from fpl_alpha.markets import consensus_from_latest_odds
from fpl_alpha.storage import open_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", action="append", type=int, required=True)
    args = parser.parse_args()

    connection = open_database()
    try:
        for fixture_id in args.fixture_id:
            probabilities = consensus_from_latest_odds(connection, fixture_id)
            if not probabilities:
                print(f"Fixture {fixture_id}: no complete match-market books.")
                continue
            print(f"Fixture {fixture_id}:")
            for probability in probabilities:
                print(
                    f"  {probability.market} {probability.outcome}: "
                    f"{probability.prob:.4f} ({probability.n_books} books)"
                )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
