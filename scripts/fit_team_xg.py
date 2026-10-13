#!/usr/bin/env python3
"""Step 4: DuckDB consensus -> fit_team_goals() -> persisted team-xG in DuckDB.

Fits Poisson team goal expectations (lambda_home, lambda_away, clean sheets, score
distribution) from latest complete odds consensus in DuckDB and stores the model
with full market provenance and fit residuals.
"""
from __future__ import annotations

import argparse

from fpl_alpha.storage import open_database
from fpl_alpha.team_xg import fit_and_persist_fixture_team_xg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", action="append", type=int, help="FPL fixture ID (repeatable)")
    parser.add_argument("--provider", default="propline", help="Odds provider (default: propline)")
    args = parser.parse_args()

    connection = open_database()
    try:
        fixture_ids = args.fixture_id
        if not fixture_ids:
            # If no fixtures specified, find fixtures with complete odds in mappings
            rows = connection.execute(
                """
                SELECT DISTINCT m.fpl_fixture_id
                FROM odds_event_fixture_mappings AS m
                WHERE m.provider_key = ? AND m.fpl_fixture_id IS NOT NULL
                ORDER BY m.fpl_fixture_id
                """,
                [args.provider],
            ).fetchall()
            fixture_ids = [r[0] for r in rows]

        if not fixture_ids:
            print(f"No fixtures found with mapped odds for provider '{args.provider}'.")
            return

        for f_id in fixture_ids:
            try:
                record = fit_and_persist_fixture_team_xg(
                    connection, f_id, provider_key=args.provider
                )
                print(
                    f"Fixture {f_id:3d} [{record.provider_key}]: "
                    f"Home xG: {record.lambda_home:.2f} (CS: {record.p_clean_sheet_home:5.1%}) | "
                    f"Away xG: {record.lambda_away:.2f} (CS: {record.p_clean_sheet_away:5.1%}) | "
                    f"Fit loss: {record.fit_loss:.6f}"
                )
                print(f"    Residuals: {record.residuals}")
            except Exception as ex:
                print(f"Fixture {f_id:3d}: skipped ({ex})")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
