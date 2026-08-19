"""Central configuration: env loading, paths, and rate-limit constants.

Everything that touches an external API reads its limits from here so the
rate-limit discipline lives in exactly one place. See CLAUDE.md — the free
tiers are tiny; never poll, always cache.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Paths ------------------------------------------------------------------
PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent.parent
DATA = REPO_ROOT / "data"
RAW = DATA / "raw"            # unmodified API responses
PROCESSED = DATA / "processed"  # normalized / joined artifacts
SNAPSHOTS = DATA / "snapshots"  # timestamped odds + FPL captures


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (stdlib only). Real env vars take precedence."""
    path = path or (REPO_ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


load_dotenv()

USER_AGENT = "fpl-alpha/0.1 (+https://github.com/RushiPardeshi)"

# --- Secrets / IDs ----------------------------------------------------------
SPORTSGAMEODDS_API_KEY = os.environ.get("SPORTSGAMEODDS_API_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
FPL_TEAM_ID = os.environ.get("FPL_TEAM_ID")
FPL_TEAM_ID_DEV2 = os.environ.get("FPL_TEAM_ID_DEV2")


@dataclass(frozen=True)
class ProviderLimits:
    """Rate-limit budget for one external source. Enforced by cache.py."""

    name: str
    base_url: str
    min_interval_s: float      # minimum seconds between live calls (throttle)
    cache_ttl_s: float         # serve cache younger than this without a live call
    note: str = ""


# Conservative defaults. Tighten, never loosen. TTLs mean "don't refetch within".
FPL_API = ProviderLimits(
    name="fpl",
    base_url="https://fantasy.premierleague.com/api",
    min_interval_s=1.0,        # be polite; endpoint can soft-ban a hammering IP
    cache_ttl_s=60 * 60 * 6,   # bootstrap changes ~daily; 6h is plenty in dev
    note="public, no key; keep <=1 req/s",
)

SPORTSGAMEODDS = ProviderLimits(
    name="sportsgameodds",
    base_url="https://api.sportsgameodds.com/v2",
    min_interval_s=6.0,        # <=10 req/min -> >=6s apart
    cache_ttl_s=60 * 10,       # upstream refreshes ~every 10 min; faster buys nothing
    note="~2500 objects/mo, 10 req/min; EPL paywalled on free tier",
)

THE_ODDS_API = ProviderLimits(
    name="the-odds-api",
    base_url="https://api.the-odds-api.com/v4",
    min_interval_s=2.0,
    cache_ttl_s=60 * 10,
    note="~500 credits/mo; credits = markets x regions per call",
)
