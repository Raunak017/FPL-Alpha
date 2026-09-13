# FPL Alpha Project Instructions

FPL Alpha is a market-informed Fantasy Premier League projection and optimization engine.

## Working Style

1. **Cache-first, always.** Every external request goes through
   `fpl_alpha.cache.fetch`. Never call `urllib`/`requests` directly from a
   stage. Never add a polling loop against any API.
2. **Respect the budgets.** Rate limits live in `config.py` (`ProviderLimits`).
   Tighten them, never loosen. The Odds API (our only odds source) bills
   `#markets × #regions` per call against a ~500-credit/mo free tier — request
   only what you use. `cache.py` tracks the real remaining credits from the
   API's `x-requests-*` response headers and warns when the budget runs low.
3. **Secrets only in `.env`** (gitignored). Never hardcode keys; never commit
   `data/`.
4. **No speculative abstractions.** Start each new stage as a single module;
   promote to a package only when it genuinely needs multiple files. Do not
   pre-create empty folders to match the plan's target tree.
   
- Keep replies very short and concise.
- Prefer implementation over long explanations.
- Do not explain work in progress; report only after the task is complete.
- Do not repeat information already established in the conversation or repository.
- Ask questions only when genuinely blocked; otherwise make a reasonable assumption and proceed.

## Token Efficiency

- Use tokens conservatively.
- Do not run unnecessary verification, validation, linting, builds, or test suites.
- Run only checks needed to validate the specific change.
- Prefer targeted tests over full test suites.
- Avoid repeatedly inspecting files or performing broad repository searches.
- Keep command output brief.
- Do not generate unnecessary documentation or comments.

## Implementation Guidance

- Follow the roadmap and architecture in `Plan.md`.
- Keep ingestion, identity mapping, market normalization, probability models, simulation, scoring, projections, and optimization modular.
- Use deterministic tests and seeded simulations where applicable.
- Keep credentials and secrets out of the repository; use `.env.example` for configuration documentation.
- Preserve existing user changes and avoid unrelated edits.

## Completion Report

At completion, report only:

- What changed
- Anything still unresolved
