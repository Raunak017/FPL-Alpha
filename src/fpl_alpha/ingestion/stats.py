"""Supplementary football stats (Plan step 1, optional).

FPL bootstrap-static already carries xG/xA/xGI, expected goals conceded, and
defensive contributions, so prefer it. This module is a placeholder for a
secondary source (e.g. FBref) only if a gap appears. Understat is anti-bot
gated and intentionally not used.

Status: intentionally empty until a concrete gap justifies a second source.
"""
from __future__ import annotations

# TODO(step 1+): add FBref pull ONLY if bootstrap-static proves insufficient.
