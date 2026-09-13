#!/usr/bin/env python3
"""Compare our market-driven GW1 xPts against FPL's own ``ep_next`` (offline).

Runs the pipeline on cached data — cached odds → team λ → availability-gated
allocation — then computes a **PARTIAL** expected-points figure per player and
lines it up against FPL bootstrap's ``ep_next`` (FPL's expected points for the
next gameweek).

⚠️ This xPts is deliberately PARTIAL — it is *not* the real engine output (the
assembler isn't built yet). It models only:

    xPts_partial = P(start)·appearance
                 + xG·goal_pts + xA·assist_pts        (from our allocator)
                 + P(start)·P(CS)·cleansheet_pts

and is MISSING bonus, defensive-contribution, saves, and the goals-conceded
penalty — plus a real minutes model (``P(start)`` here is a crude proxy:
fitness × last-season start rate). So expect our numbers to sit BELOW ep_next for
defenders/keepers (we omit their biggest components) and to over-rate fit-but-
rotated attackers. Read this as a directional / rank sanity check, not a
precision benchmark.

    PYTHONPATH=src python scripts/compare_ep_next.py
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fpl_alpha.allocation import allocate_fixture, attack_weights_from_bootstrap
from fpl_alpha.config import RAW
from fpl_alpha.identity import match_odds_name, teams_from_bootstrap
from fpl_alpha.ingestion import fpl, odds
from fpl_alpha.markets import consensus
from fpl_alpha.minutes import availability_factor, start_probability
from fpl_alpha.schemas import PlayerFixtureProjection, ProjectionRun
from fpl_alpha.scoring import CURRENT_RULESET
from fpl_alpha.storage import (
    open_database,
    persist_projection_run,
    select_gameweek_projection_run,
)
from fpl_alpha.team_xg import fit_team_goals

# --- Minimal FPL scoring constants (partial; lives here, not in the engine) --
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_PTS = 3
APPEARANCE_PTS = 2  # assume a starter plays 60'+
MODEL_NAME = "partial_xpts"
MODEL_VERSION = "0.1.1"


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --- stdlib correlation helpers ---------------------------------------------
def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx > 0 and sy > 0 else float("nan")


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_ranks(xs), _ranks(ys))


def _parse_as_of(value: str) -> datetime:
    """Parse an explicit, timezone-aware projection observation timestamp."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--as-of must include a timezone, e.g. 2026-08-21T17:30:00Z")
    return parsed


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _next_gameweek(bootstrap: dict) -> int:
    next_events = [event["id"] for event in bootstrap.get("events", []) if event.get("is_next")]
    if len(next_events) != 1:
        raise ValueError("pass --gameweek when bootstrap does not identify exactly one next gameweek")
    return next_events[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", action="store_true", help="persist this partial projection run to DuckDB")
    ap.add_argument("--gameweek", type=int, help="target FPL gameweek; required if --store and no next GW")
    ap.add_argument("--as-of", type=_parse_as_of, help="explicit ISO-8601 forecast timestamp")
    ap.add_argument(
        "--select",
        action="store_true",
        help="set this run as the selected decision forecast for its gameweek (requires --store)",
    )
    args = ap.parse_args()
    if args.select and not args.store:
        ap.error("--select requires --store")
    if args.store and args.as_of is None:
        ap.error("--store requires --as-of so the forecast is reproducible")

    bootstrap_path = RAW / "fpl" / "bootstrap-static.json"
    odds_path = RAW / "the-odds-api" / "theoddsapi-epl-h2h+totals-uk.json"
    boot = json.loads(bootstrap_path.read_text())
    teams = teams_from_bootstrap(boot)
    rates = attack_weights_from_bootstrap(boot)  # shrunk + minutes-weighted

    el = {e["id"]: e for e in boot["elements"]}
    events = json.loads(odds_path.read_text())
    fixtures = odds.parse_the_odds_api_events(events)

    target_gameweek = args.gameweek
    fixture_ids: dict[tuple[int, int], int] = {}
    if args.store:
        target_gameweek = target_gameweek or _next_gameweek(boot)
        fpl_fixtures_path = RAW / "fpl" / "fixtures.json"
        fpl_fixtures = fpl.fixtures_from_api(json.loads(fpl_fixtures_path.read_text()))
        fixture_ids = {
            (fixture.team_h_fpl_id, fixture.team_a_fpl_id): fixture.fpl_id
            for fixture in fpl_fixtures
            if fixture.event == target_gameweek
        }
        if not fixture_ids:
            raise ValueError(f"no cached FPL fixtures found for gameweek {target_gameweek}")

    rows: list[dict] = []
    unmatched_fixtures: list[str] = []
    for fo in fixtures:
        home = match_odds_name(fo.home_team, teams)
        away = match_odds_name(fo.away_team, teams)
        if home is None or away is None:
            if args.store:
                unmatched_fixtures.append(f"{fo.home_team} v {fo.away_team} (unmatched team name)")
            continue
        fixture_fpl_id = fixture_ids.get((home.fpl_id, away.fpl_id)) if args.store else None
        if args.store and fixture_fpl_id is None:
            unmatched_fixtures.append(f"{fo.home_team} v {fo.away_team} (no FPL fixture in GW {target_gameweek})")
            continue
        fid = f"{home.short_name}_v_{away.short_name}"
        mps = consensus(fid, "h2h", ["home", "draw", "away"], fo.h2h)
        if fo.totals:
            mps += consensus(fid, f"totals_{fo.totals_line}", ["over", "under"], fo.totals)
        model = fit_team_goals(fid, home.fpl_id, away.fpl_id, mps)
        cs = {home.fpl_id: model.p_clean_sheet_home, away.fpl_id: model.p_clean_sheet_away}

        for r in allocate_fixture(model, rates):
            e = el[r.fpl_id]
            pos = POS.get(e["element_type"], "UNK")
            # P(start) from the step-7 minutes model (fitness × shrunk start rate).
            p_start = start_probability(
                _f(e.get("starts")), _f(e.get("minutes")),
                availability_factor(e.get("status"), e.get("chance_of_playing_next_round")),
            )
            xpts = (
                p_start * APPEARANCE_PTS
                + r.exp_goals * GOAL_PTS.get(pos, 0)
                + r.exp_assists * ASSIST_PTS
                + p_start * cs[r.team_fpl_id] * CS_PTS.get(pos, 0)
            )
            rows.append({
                "player_fpl_id": r.fpl_id,
                "fixture_fpl_id": fixture_fpl_id,
                "name": e["web_name"], "team": home.short_name if r.team_fpl_id == home.fpl_id else away.short_name,
                "pos": pos, "ours": xpts, "ep_next": _f(e.get("ep_next")),
                "xg": r.exp_goals, "xa": r.exp_assists, "p_start": p_start, "p_cs": cs[r.team_fpl_id],
                "appearance_points": p_start * APPEARANCE_PTS,
                "goal_points": r.exp_goals * GOAL_PTS.get(pos, 0),
                "assist_points": r.exp_assists * ASSIST_PTS,
                "clean_sheet_points": p_start * cs[r.team_fpl_id] * CS_PTS.get(pos, 0),
            })

    if args.store and unmatched_fixtures:
        raise ValueError("cannot persist an incomplete gameweek: " + "; ".join(unmatched_fixtures))
    if args.store and target_gameweek is not None:
        fingerprint_payload = {
            "gameweek": target_gameweek,
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "scoring_rules_version": CURRENT_RULESET.version,
            "as_of": args.as_of.isoformat(),
            "bootstrap_sha256": _file_digest(bootstrap_path),
            "odds_sha256": _file_digest(odds_path),
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode()
        ).hexdigest()
        run = ProjectionRun(
            run_id=str(uuid4()),
            gameweek=target_gameweek,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            scoring_rules_version=CURRENT_RULESET.version,
            input_fingerprint=fingerprint,
            as_of=args.as_of,
            created_at=args.as_of,
            is_partial=True,
            notes="Appearance, attacking, and clean-sheet terms only.",
        )
        projections = [
            PlayerFixtureProjection(
                run_id=run.run_id,
                gameweek=target_gameweek,
                player_fpl_id=row["player_fpl_id"],
                fixture_fpl_id=row["fixture_fpl_id"],
                expected_points=row["ours"],
                expected_goals=row["xg"],
                expected_assists=row["xa"],
                p_start=row["p_start"],
                p_clean_sheet=row["p_cs"],
                appearance_points=row["appearance_points"],
                goal_points=row["goal_points"],
                assist_points=row["assist_points"],
                clean_sheet_points=row["clean_sheet_points"],
            )
            for row in rows
        ]
        connection = open_database()
        try:
            stored_run_id = persist_projection_run(connection, run, projections)
            if args.select:
                select_gameweek_projection_run(
                    connection,
                    target_gameweek,
                    stored_run_id,
                    args.as_of,
                    selection_reason="explicitly selected by projection run",
                )
        finally:
            connection.close()
        print(f"Stored partial projection run {stored_run_id} for GW{target_gameweek} ({len(projections)} rows).")

    print(__doc__.split("\n\n")[0])
    print(f"\n{len(rows)} players across {sum(1 for _ in fixtures)} GW1 fixtures "
          f"(cached, availability-gated).\n")

    # (a) Top 20 by OUR partial xPts
    print("=" * 74)
    print("TOP 20 BY OUR PARTIAL xPts   (ours | ep_next | Δ)")
    print("=" * 74)
    for r in sorted(rows, key=lambda r: r["ours"], reverse=True)[:20]:
        d = r["ours"] - r["ep_next"]
        print(f"  {r['name']:18} {r['team']:4} {r['pos']:3}  "
              f"{r['ours']:5.2f} | {r['ep_next']:5.2f} | {d:+5.2f}")

    # (b) Top 20 by FPL's ep_next — who FPL rates that we (mis)rank
    print("\n" + "=" * 74)
    print("TOP 20 BY FPL ep_next        (ours | ep_next | Δ)")
    print("=" * 74)
    for r in sorted(rows, key=lambda r: r["ep_next"], reverse=True)[:20]:
        d = r["ours"] - r["ep_next"]
        print(f"  {r['name']:18} {r['team']:4} {r['pos']:3}  "
              f"{r['ours']:5.2f} | {r['ep_next']:5.2f} | {d:+5.2f}")

    # (c) Position breakdown — where we systematically diverge
    print("\n" + "=" * 74)
    print("MEAN BY POSITION (players with ep_next > 0)")
    print("=" * 74)
    for pos in ("GKP", "DEF", "MID", "FWD"):
        sub = [r for r in rows if r["pos"] == pos and r["ep_next"] > 0]
        if sub:
            mo = sum(r["ours"] for r in sub) / len(sub)
            me = sum(r["ep_next"] for r in sub) / len(sub)
            print(f"  {pos}:  ours {mo:4.2f}   ep_next {me:4.2f}   Δ {mo - me:+4.2f}   (n={len(sub)})")

    # (d) Correlation on the players that matter for selection
    print("\n" + "=" * 74)
    print("CORRELATION vs ep_next")
    print("=" * 74)
    for label, sub in (
        ("all slate players", rows),
        ("ep_next >= 3.0 (selection-relevant)", [r for r in rows if r["ep_next"] >= 3.0]),
        ("MID + FWD, ep_next >= 3.0", [r for r in rows if r["pos"] in ("MID", "FWD") and r["ep_next"] >= 3.0]),
    ):
        if len(sub) >= 2:
            o = [r["ours"] for r in sub]
            e_ = [r["ep_next"] for r in sub]
            print(f"  {label:38} n={len(sub):3}  "
                  f"Pearson {_pearson(o, e_):+.2f}  Spearman {_spearman(o, e_):+.2f}")


if __name__ == "__main__":
    main()
