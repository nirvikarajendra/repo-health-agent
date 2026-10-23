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
- Postgres 18 (pgvector image `pgvector/pgvector:0.8.7-pg18`) in Docker Compose and CI; `psycopg` v3; plain SQL (no ORM)
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
- Collect repos into Postgres: `uv run python -m repo_health.collector OWNER/REPO [OWNER/REPO ...]` (a failed repo is skipped; exit code 1 if any failed)

## Layout
- `pyproject.toml`: project metadata, dev dependencies (pytest, ruff), ruff config
- `uv.lock`: exact pinned versions; commit it, never edit by hand
- `src/repo_health/`: the `repo_health` package
  - `config.py`: settings from environment variables / `.env` (Pydantic Settings)
  - `db.py`: Postgres connection; `migrate.py`: applies new files from `sql/migrations/`
  - `logs.py`: `setup_logging()` for the command-line entry points (terminal + `logs/` file)
  - `collector/`: GitHub API → Postgres (plain Python, not an agent). `github.py` is the read-only client (paging, rate limits); `repos.py`, `issues.py`, `pulls.py`, `reviews.py`, `releases.py` and `commits.py` each fetch, parse and upsert one kind of data; `sync_runs.py` records each run (status, requests, error, `repo_id`); `__main__.py` runs every step.
  - `metrics/`: one SQL query + one Python function per metric. `models.py` has the Pydantic results (`Metric`, `TrackedRepo`, `RepoOverview`, `FirstResponseTime`, `BugCloseRate`, `PrReviewTime`); `list_repos.py` lists tracked repos with their latest successful sync time; `repo_overview.py` returns one repo's stats (name matched ignoring case); `first_response_time.py` returns the median hours to a maintainer's first comment on outside issues, plus the unanswered ones (issues only, not Discussions); `bug_close_rate.py` returns the share of bug-labelled issues closed as completed within 30 days, with the counts behind it and how many issues carry a bug label; `pr_review_time.py` returns the median hours to a maintainer's first review on outside PRs, plus the unreviewed ones (merged / closed / still open). `data_as_of` always comes from the `repo_data_as_of` view (migration 003), never re-derived.
  - `agent/`: ADK agent and its tools. Empty so far.
- `logs/`: run logs, one file per day (`YYYY-MM-DD.log`, appended). Git-ignored.
- `sql/migrations/`: numbered schema files (`001_initial_schema.sql`, …). Add a new file; never edit an applied one.
- `tests/`: unit tests (no network, no real LLM calls). `conftest.py` has the shared fixtures (`load_fixture`, `fake_conn`, `fake_github`); `fixtures/github/` holds trimmed real API responses. `db_conn` connects to `TEST_DATABASE_URL` (its name must end in `_test`; every test empties it, and the tests are skipped if it is unset); `test_sql.py` runs the real SQL against it.
- `docs/architecture.md`: full design; `docs/development.md`: setup and workflow
- `.claude/skills/add-collector-endpoint/`: step-by-step recipe for adding a new GitHub endpoint to the collector
- `.claude/skills/add-metric/`: recipe for adding a metric tool; `definitions.md` holds the exact metric rules
- Not created yet: `evals/` (questions, code-computed gold answers, eval runner)

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
