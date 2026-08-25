# FPL Alpha Project Instructions

FPL Alpha is a market-informed Fantasy Premier League projection and optimization engine.

## Working Style

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
