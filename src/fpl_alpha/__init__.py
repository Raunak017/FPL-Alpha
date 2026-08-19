"""FPL Alpha — market-informed FPL projection & optimization engine.

Pipeline (see docs/PROJECT_PLAN.md):
    ingestion -> identity -> markets -> team_xg -> models -> simulation
    -> scoring -> projections -> optimization -> evaluation

Downstream stages (simulation onward) are added when reached; the plan reserves
their names but empty packages are intentionally omitted for now.
"""

__version__ = "0.1.0"
