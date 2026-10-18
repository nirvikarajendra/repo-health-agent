# repo-health-agent

An AI agent that answers "Is this open-source library well maintained?" using GitHub data.
It reports general repo stats and maintenance metrics (response times, bug close rate, PR review time, release cadence, contributors), and every number is computed by code.

Full design: @docs/architecture.md. Read it before changing data, tables, metrics or tools.

## Who you're working with
- I'm a beginner learning as I build. For every change, tell me in 1 to 3 sentences **why**, not just what.
- Work in small steps. Do one thing, show me how to verify it, then stop and wait for me.
- Don't add features, files, libraries or agents that weren't asked for. If you think the scope is wrong, say so once, then do what was asked.

## Stack (don't change without asking)
- Python 3.12, managed with **uv** (`uv add`, `uv run`). Never use pip directly.
- Google ADK + Gemini (free tier, model name comes from config, never hard-coded)
- Postgres 16 in Docker Compose; `psycopg` v3; plain SQL (no ORM)
- Pydantic v2 for every tool input/output
- pytest, ruff (lint + format), GitHub Actions
- Free and free-tier only. Ask before adding anything that costs money.

## Commands
- Install: `uv sync`
- Add a dependency: `uv add <pkg>` (dev-only: `uv add --dev <pkg>`)
- Tests: `uv run pytest`
- Lint/format: `uv run ruff check . --fix && uv run ruff format .`
- Lint/format check only (no changes): `uv run ruff check . && uv run ruff format --check .`
- Apply DB migrations: `uv run python -m repo_health.migrate`

## Layout
- `pyproject.toml`: project metadata, dev dependencies (pytest, ruff), ruff config
- `uv.lock`: exact pinned versions; commit it, never edit by hand
- `src/repo_health/`: the `repo_health` package
  - `collector/`: GitHub API → Postgres (plain Python, not an agent). Empty so far.
  - `metrics/`: one SQL query + one Python function per metric. Empty so far.
  - `agent/`: ADK agent and its tools. Empty so far.
- `tests/`: unit tests (no network, no real LLM calls). `test_smoke.py` checks the package imports.
- `docs/architecture.md`: full design
- Not created yet: `sql/` (schema and migrations), `evals/` (questions, code-computed gold answers, eval runner)

## Rules that matter
- **Agent is read-only.** Agent tools use the read-only DB role and only run fixed, parameterised SQL. No string-formatted SQL, ever.
- **Numbers come from code, not the LLM.** Every number in an agent answer must come from a tool result.
- **Gold answers for evals are computed by code**, never written by an LLM.
- **Never write to GitHub.** The collector uses GET requests only.
- **Secrets:** read from environment variables or `.env` (which is git-ignored). Never print, log or commit keys. Never open `.env`.
- **Tests:** every metric and tool gets a unit test against a small fixture dataset. Tests never call GitHub or Gemini; mock them.
- **Before saying a task is done:** run tests and lint, and show me the output.

## Out of scope for v1
Summarising issue/README text, security/vulnerability checks, predictions, ranking maintainers, private repos, any write action.
