# Development guide

## Prerequisites
- Python 3.12 (managed by [uv](https://docs.astral.sh/uv/))
- Docker with Compose v2
- Git and, optionally, the GitHub CLI (`gh`)

## Quick start
```bash
git clone https://github.com/<you>/repo-health-agent.git
cd repo-health-agent
uv sync                                   # install dependencies from uv.lock
cp .env.example .env                      # then set POSTGRES_PASSWORD (and the same password in both *_URL lines)
docker compose up -d                      # start Postgres
docker compose exec db createdb -U repo_health repo_health_test   # once, for tests/test_sql.py
uv run python -m repo_health.migrate      # apply DB migrations
uv run pytest                             # run tests
uv run python -m repo_health.collector encode/httpx   # collect one or more OWNER/REPO into Postgres
```

## Project layout
```
src/repo_health/
  config.py      settings from environment variables / .env
  db.py          Postgres connection
  migrate.py     applies new files from sql/migrations/
  logs.py        setup_logging(): terminal + logs/ file
  collector/     GitHub API → Postgres (plain Python)
  metrics/       one SQL query + function per metric (list_repos, repo_overview, first_response_time, bug_close_rate, pr_review_time, release_cadence, contributor_stats)
  agent/         ADK agent and its tools (not started)
logs/            run logs, one file per day (YYYY-MM-DD.log); git-ignored
sql/migrations/  numbered schema files; add new ones, never edit applied ones
tests/           unit tests (no network, no real LLM calls)
  conftest.py    shared fixtures: load_fixture, fake_conn, fake_github, db_conn (real test DB)
  test_sql.py    real SQL against TEST_DATABASE_URL (name must end in _test)
  fixtures/      trimmed real GitHub API responses
docs/            architecture and development docs
.claude/         Claude Code settings, hooks and skills
.github/         CI workflows
compose.yaml     local Postgres (pgvector image)
```

## Workflow
- `main` is protected: changes land only through pull requests.
- CI must pass before merge: lint, format check, tests, secret scan.
- One branch per step or feature, squash-merged into `main`.

```bash
git switch main && git pull
git switch -c <feature-branch>
# work, commit
git push -u origin <feature-branch> && gh pr create --fill
```

## Checks (same as CI)
```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Configuration
All settings come from environment variables in `.env`. The file is git-ignored, and `.env.example` lists every variable.

| Variable | Purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local database |
| `DATABASE_URL` | Connection string the app and migrations use to reach Postgres |
| `TEST_DATABASE_URL` | Test database for `tests/test_sql.py`; name must end in `_test` (wiped by every test). Unset: those tests are skipped |
| `GITHUB_TOKEN` | Fine-grained, read-only token for public repos |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | LLM access (free tier) |

## AI-assisted development (Claude Code)
- `CLAUDE.md`: project rules: stack, layout, coding rules, scope.
- `CLAUDE.local.md`: personal preferences (git-ignored).
- `.claude/settings.json`:
  - Deny rules: no reading or editing `.env`, and no editing Claude's own settings or hooks.
  - A post-edit hook runs ruff on every Python file Claude changes.
- `.claude/skills/add-collector-endpoint/`: run `/add-collector-endpoint <endpoint>` to add a new GitHub endpoint (plan → fixture → code → tests, with a stop for review after each step).

## Key decisions
| Decision | Reason |
|---|---|
| uv instead of pip/venv | One tool for Python versions, dependencies and lock file; fast and reproducible |
| Plain parameterised SQL, no ORM | Metrics are analytical queries (medians, window functions); the SQL is the metric definition |
| Postgres with pgvector image | Not used in v1; kept for the planned issue-summariser agent (vector search over issue text) |
| Fixed metric tools instead of LLM-written SQL | Deterministic, testable numbers; the agent can't run arbitrary queries |
| Data snapshot in Postgres | Repeatable answers for evals; no rate-limit pressure at question time |
