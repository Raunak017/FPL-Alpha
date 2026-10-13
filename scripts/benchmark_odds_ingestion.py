#!/usr/bin/env python3
"""Benchmark odds ingestion performance and memory across varying dataset sizes."""
from __future__ import annotations

import gc
import resource
import time
import tracemalloc
import multiprocessing
from datetime import datetime, timezone

from fpl_alpha.schemas import (
    Fixture,
    OddsBookmaker,
    OddsEventFixtureMapping,
    OddsOutcomeSnapshot,
    OddsPlayerMapping,
    OddsProviderEvent,
    Team,
)
from fpl_alpha.storage import (
    open_database,
    store_odds_snapshot_bundle,
    upsert_fixtures,
    upsert_teams,
)


def _generate_synthetic_bundle(
    n_records: int, captured_at: datetime
) -> tuple[
    list[OddsProviderEvent],
    list[OddsEventFixtureMapping],
    list[OddsPlayerMapping],
    list[OddsBookmaker],
    list[OddsOutcomeSnapshot],
]:
    events = [
        OddsProviderEvent(
            provider_key="propline",
            provider_event_id=f"evt_{i}",
            sport_key="soccer_epl",
            home_team="Arsenal",
            away_team="Chelsea",
            commence_time="2026-08-21T19:00:00Z",
        )
        for i in range(10)
    ]
    mappings = [
        OddsEventFixtureMapping(
            provider_key="propline",
            provider_event_id=f"evt_{i}",
            fpl_fixture_id=99,
            match_method="home_away_kickoff_exact",
        )
        for i in range(10)
    ]
    bookmakers = [
        OddsBookmaker(provider_key="propline", bookmaker_key=f"book_{i}", title=f"Bookmaker {i}")
        for i in range(5)
    ]
    player_mappings = [
        OddsPlayerMapping(
            provider_key="propline",
            provider_event_id="evt_0",
            selection_description=f"Player {i}",
            fpl_player_id=100 + (i % 50),
            match_method="explicit_alias",
        )
        for i in range(min(500, n_records))
    ]

    snapshots = [
        OddsOutcomeSnapshot(
            provider_key="propline",
            provider_event_id=f"evt_{i % 10}",
            bookmaker_key=f"book_{i % 5}",
            market_key=f"mkt_{i % 25}",
            market_ordinal=i,
            market_description="Market Description",
            market_team="Arsenal" if (i % 2 == 0) else "Chelsea",
            outcome_ordinal=i % 10,
            selection_description=f"Player {i}" if (i % 3 == 0) else None,
            fpl_player_id=(100 + (i % 50)) if (i % 3 == 0) else None,
            outcome_name=f"Outcome {i % 10}",
            american_price=-110 + (i % 200),
            point=2.5 if (i % 5 == 0) else None,
            last_update=None,
            last_change_at=None,
            captured_at=captured_at,
        )
        for i in range(n_records)
    ]
    return events, mappings, player_mappings, bookmakers, snapshots


def _run_benchmark_worker(n_records: int, queue: multiprocessing.Queue) -> None:
    gc.collect()
    con = open_database(":memory:")
    upsert_teams(con, [Team(1, "Arsenal", "ARS"), Team(2, "Chelsea", "CHE")])
    upsert_fixtures(
        con,
        [
            Fixture(
                fpl_id=99,
                code=1001,
                event=1,
                kickoff_time="2026-08-21T19:00:00Z",
                finished=False,
                finished_provisional=False,
                minutes=0,
                provisional_start_time=False,
                started=False,
                team_a_fpl_id=2,
                team_a_score=None,
                team_a_difficulty=3,
                team_h_fpl_id=1,
                team_h_score=None,
                team_h_difficulty=2,
            )
        ],
    )

    t_capture = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    events, mappings, player_mappings, bookmakers, snapshots = _generate_synthetic_bundle(
        n_records, t_capture
    )

    tracemalloc.start()
    t0 = time.perf_counter()
    run = store_odds_snapshot_bundle(
        con,
        provider_key="propline",
        events=events,
        event_fixture_mappings=mappings,
        player_mappings=player_mappings,
        bookmakers=bookmakers,
        snapshots=snapshots,
    )
    t_total = time.perf_counter() - t0
    current_mem, peak_tracemalloc = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Peak RSS (resident memory) in this fresh child process
    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)

    # Test idempotent re-ingestion time
    t_retry_start = time.perf_counter()
    retry_run = store_odds_snapshot_bundle(
        con,
        provider_key="propline",
        events=events,
        event_fixture_mappings=mappings,
        player_mappings=player_mappings,
        bookmakers=bookmakers,
        snapshots=snapshots,
    )
    t_retry = time.perf_counter() - t_retry_start

    db_rows = con.execute("SELECT count(*) FROM odds_outcome_snapshots").fetchone()[0]
    con.close()

    result = {
        "n_records": n_records,
        "run_id": run.run_id,
        "total_time_s": round(t_total, 3),
        "retry_time_s": round(t_retry, 3),
        "peak_tracemalloc_mb": round(peak_tracemalloc / (1024 * 1024), 2),
        "peak_rss_mb": round(peak_rss_mb, 2),
        "db_rows": db_rows,
        "records_inserted": run.records_inserted,
        "records_updated": retry_run.records_updated,
        "is_retry": retry_run.is_retry,
        "retry_of_run_id": retry_run.retry_of_run_id,
    }
    queue.put(result)


def run_benchmark(n_records: int) -> dict[str, float | int | str]:
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_run_benchmark_worker, args=(n_records, queue))
    proc.start()
    result = queue.get()
    proc.join()
    return result


def main():
    sizes = [27_000, 100_000, 250_000]
    print(f"{'Rows':>8} | {'Total Time (s)':>15} | {'Retry Time (s)':>15} | {'Tracemalloc Peak':>17} | {'Peak RSS':>12} | {'DB Rows':>9}")
    print("-" * 88)
    for n in sizes:
        res = run_benchmark(n)
        print(
            f"{res['n_records']:>8,d} | "
            f"{res['total_time_s']:>15.3f} | "
            f"{res['retry_time_s']:>15.3f} | "
            f"{res['peak_tracemalloc_mb']:>14.2f} MB | "
            f"{res['peak_rss_mb']:>9.2f} MB | "
            f"{res['db_rows']:>9,d}"
        )


if __name__ == "__main__":
    main()
