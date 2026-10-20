---
name: add-collector-endpoint
description: Add a new GitHub REST endpoint to the repo-health collector (fetch → parse → upsert, with fixture and mocked tests). Use when asked to collect a new kind of GitHub data, e.g. pull requests, reviews, releases or commits.
argument-hint: "<endpoint, e.g. /repos/{owner}/{repo}/releases>"
---

# Add a collector endpoint: $ARGUMENTS

Copy the shape of `src/repo_health/collector/issues.py` and `tests/test_collector_issues.py`. Stop at each **Checkpoint** and wait for the user. If no endpoint is given, ask which one.

## 1. Plan
Read [fields.md](fields.md) and the table in `sql/migrations/`. Store only the listed fields, never `body`/`title`. Every `NOT NULL` column needs a value. A missing table means a **new** migration file; never edit an applied one.

**Checkpoint:** show fields → columns and how the data is limited.

## 2. Fixture
If `tests/fixtures/github/<name>.json` exists, use it instead. Otherwise fetch 5 items **without a token** (never read `.env`), and only replace the fixture if it worked:
```bash
curl -sf -H "X-GitHub-Api-Version: <API_VERSION in collector/github.py>" \
  "https://api.github.com/repos/<owner>/<repo>/<endpoint>?per_page=5" | uv run python -m json.tool > /tmp/<name>.json \
  && mv /tmp/<name>.json tests/fixtures/github/<name>.json
```
If rate-limited, ask the user to run it in their own terminal with their token (never ask them to share it).

Either way, remove free-text fields (`body`, `title`, `name`, `commit.message`) from the fixture.

**Checkpoint:** show the field names.

## 3. Code
In `collector/<area>.py`: `parse_<thing>` (pure, `.get()` for nullable fields), `UPSERT_<THING>` (parameterised, `ON CONFLICT`), `collect_<things>` (one `executemany` per page, returns distinct count; limit the data as fields.md says). Wire it into `__main__.py` with `conn.commit()`.

**Checkpoint:** show the code.

## 4. Tests
Use the `load_fixture`, `fake_conn` and `fake_github` fixtures from `tests/conftest.py`. Test parsing, one edge case (e.g. null user) and `collect_*` (rows, count, required columns not None; 2 pages if it stops paging).

## 5. Finish
Run `uv run ruff format . && uv run ruff check . && uv run pytest` and show the output. Then give the user the collector command and a SQL query to check the new table.
