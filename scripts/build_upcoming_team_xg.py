#!/usr/bin/env python3
"""Build team-xG projections for all mapped future fixtures with PropLine odds."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from fpl_alpha.storage import load_fixtures, load_teams, open_database
from fpl_alpha.team_xg import (
    build_and_persist_team_goal_projection,
    upcoming_fixture_ids_with_odds,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-key", default="propline")
    args = parser.parse_args()

    connection = open_database()
    try:
        teams = {team.fpl_id: team.name for team in load_teams(connection)}
        fixtures = {fixture.fpl_id: fixture for fixture in load_fixtures(connection)}
        fixture_ids = upcoming_fixture_ids_with_odds(
            connection, args.provider_key, datetime.now(timezone.utc)
        )
        built = []
        skipped = []

        connection.execute("BEGIN TRANSACTION")
        try:
            for fixture_id in fixture_ids:
                try:
                    projection = build_and_persist_team_goal_projection(
                        connection, fixture_id, args.provider_key
                    )
                except ValueError as error:
                    if str(error).startswith("no complete match-market consensus"):
                        skipped.append((fixture_id, str(error)))
                        continue
                    raise
                built.append(projection)
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
    finally:
        connection.close()

    print(f"Mapped upcoming fixtures with odds: {len(fixture_ids)}")
    print(f"Built consensus and team-xG projections ({len(built)}):")
    for projection in built:
        fixture = fixtures[projection.fixture_fpl_id]
        books = {
            comparison.market: comparison.n_books
            for comparison in projection.comparisons
        }
        print(
            f"  {projection.fixture_fpl_id}: "
            f"{teams[fixture.team_h_fpl_id]} v {teams[fixture.team_a_fpl_id]} — "
            f"xG {projection.model.lambda_home:.2f}/{projection.model.lambda_away:.2f}; "
            f"books h2h={books.get('h2h', 0)}, "
            f"btts={books.get('btts', 0)}, totals={books.get('totals_2.5', 0)}"
        )
    print(f"Skipped ({len(skipped)}):")
    for fixture_id, reason in skipped:
        fixture = fixtures[fixture_id]
        print(
            f"  {fixture_id}: {teams[fixture.team_h_fpl_id]} v "
            f"{teams[fixture.team_a_fpl_id]} — {reason}"
        )


if __name__ == "__main__":
    main()
