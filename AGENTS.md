# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/matrusp_mcp/`. Scheduling/domain logic is separate from
persistence, snapshots, and transport adapters. JupiterWeb collection and parsing belong in
`src/matrusp_mcp/crawler/`. Tests mirror these areas in `tests/test_*.py`.
`data/matrusp.sqlite` is a development snapshot; automation lives in
`.github/workflows/`.

## Python & uv Environment

- uv is the sole environment and dependency manager. Do not use global `python` or `pip`, or
  manually modify `.venv/`.
- Use Python 3.12 from `.python-version` and the uv version required by `pyproject.toml`. Do
  not update uv automatically; change its constraint and CI pins together.
- Bootstrap with `uv sync --locked`. Run commands through `uv run --locked` so routine
  work cannot rewrite `uv.lock`.
- Use `uv add`, `uv add --dev`, and `uv remove` for dependencies. Commit `pyproject.toml` and
  `uv.lock` together; reserve `uv lock --upgrade` for intentional upgrades.

## Build, Test, and Development Commands

- `uv run --locked matrusp-mcp validate data/matrusp.sqlite` verifies the bundled snapshot.
- `uv run --locked matrusp-mcp serve --transport stdio --snapshot data/matrusp.sqlite` starts
  the local server; substitute `streamable-http` for HTTP.
- `uv run --locked pytest --cov=matrusp_mcp --cov-branch` runs tests and the coverage gate.
- `uv run --locked ruff check .` and `uv run --locked pyright` run lint and type checks.
- `uv build` builds distributions; `docker build --tag matrusp-mcp:test .` builds the image.

## Coding Style & Naming Conventions

Use four-space indentation, Python 3.12 syntax, annotations, and Ruff's 100-character
line length. Use `snake_case` for modules/functions, `PascalCase` for classes, and
`UPPER_SNAKE_CASE` for constants. Fix type errors instead of adding suppressions. Keep domain
logic independent of HTML, SQLite, and transport concerns.

## Testing Guidelines

Use pytest, pytest-asyncio, Hypothesis, and pytest-cov. Name tests `test_<behavior>` and add
regressions, including edge cases, for behavior changes. Branch coverage must remain at least
90%. Normal tests are network-free. Live contracts are opt-in: install Chromium with
`uv run --locked playwright install chromium`, then run
`MATRUSP_RUN_LIVE_CONTRACT=1 uv run --locked pytest -m live_contract`.

## Commit & Pull Request Guidelines

Use Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `build:`, `ci:`, or
`chore:`. Write a specific imperative subject and a detailed body covering motivation,
technical changes, and verification. Keep generated snapshots separate from code changes.
Pull requests should link issues and highlight schema, API, crawler, or snapshot changes.

## Security & Data Integrity

The runtime must remain read-only and offline. Preserve immutable SQLite access, snapshot
validation, HTTP Host/Origin checks, and release provenance. Never commit credentials or
production-only configuration.
