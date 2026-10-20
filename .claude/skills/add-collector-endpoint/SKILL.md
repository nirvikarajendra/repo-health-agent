---
name: add-collector-endpoint
description: Add a new GitHub REST endpoint to the repo-health collector (fetch → parse → upsert, with fixture and mocked tests). Use when asked to collect a new kind of GitHub data, e.g. pull requests, reviews, releases or commits.
argument-hint: "<endpoint, e.g. /repos/{owner}/{repo}/releases>"
---

# Add a collector endpoint

The endpoint to add is: $ARGUMENTS

Every endpoint follows the same pattern as `src/repo_health/collector/issues.py`. Read that file and `tests/test_collector_issues.py` first and copy their shape.

## 0. Plan, then stop
- Read `docs/architecture.md` (which metric tool needs this data) and [fields.md](fields.md) (which fields to store and how to limit the data).
- Store **only** those fields. Never store `body`, `title` or other free text (prompt-injection risk; out of scope for v1).
- Check `sql/migrations/` already has a table with those columns. If not, plan a **new** file `NNN_<what>.sql` (next number). Never edit a migration that is already applied: `migrate.py` tracks files by name, so the edit would silently never run.
- Decide: does the endpoint return **one object** (`get_json`) or a **list** (`iter_pages`)? How is the data limited (`since`, or sort by updated and stop paging)?
- Remember the stale-data trap: if open items matter for a metric, fetch **all open** items without a date filter, plus recent ones.

**Checkpoint:** show the user the plan (fields → columns, table or new migration, `get_json`/`iter_pages`, how results are limited) and wait for approval.

## 1. Fixture, then stop
Save a small real response. The data is public, so fetch it **without a token**. Never ask the user for the token, and never read `.env`.
```bash
API_VERSION=$(uv run python -c "from repo_health.collector.github import API_VERSION; print(API_VERSION)")
curl -sf -H "X-GitHub-Api-Version: $API_VERSION" \
  "https://api.github.com/<endpoint>?per_page=5" | uv run python -m json.tool > /tmp/<name>.json \
  && mv /tmp/<name>.json tests/fixtures/github/<name>.json
```
The API version comes from `github.py`, so fixtures always match what the collector receives. `-f` makes curl fail on an HTTP error, and writing to `/tmp` first means a failed fetch never empties an existing fixture. If it fails, ask the user to run the same command in **their own terminal** after `set -a; source .env; set +a`, adding `-H "Authorization: Bearer $GITHUB_TOKEN"`.

Then **trim** the fixture: keep only the fields the parser reads, plus ones needed for edge cases (`user`, nested objects). Remove `body`, `title` and other free text.

**Checkpoint:** show the user the fixture's field names and nesting (e.g. `user.login`, `commit.author.date`) and wait for approval before writing the parser.

## 2. Code, in `src/repo_health/collector/<area>.py`
1. `parse_<thing>(item: dict) -> dict`: pure function, JSON → one row. Use `.get()` for fields that can be missing or null; `(item.get("user") or {}).get("login")` for users (deleted users are `null`).
2. `UPSERT_<THING>`: plain parameterised SQL, `INSERT ... ON CONFLICT (<primary key>) DO UPDATE SET ...`. Never build SQL with f-strings.
3. `collect_<things>(conn, client, repo_id, ...) -> int`: loop over `iter_pages`, parse each page, `cur.executemany(UPSERT, rows)` per page, return the number of **distinct** keys saved. The default extra arguments are `full_name, since`, but the "Limiting the data" column in [fields.md](fields.md) wins:
   - no `since` support (releases): drop the `since` argument and fetch everything.
   - sort and stop (pulls): `break` out of the page loop once an item's `updated_at` is older than `since`.
   - one call per parent (reviews): take the parent keys (e.g. PR numbers saved in this run) instead of `since`, and loop over them.
4. Wire it into `collector/__main__.py` after the existing steps, followed by `conn.commit()` and a `print` of the count.

**Checkpoint:** show the user the new code and run `uv run ruff check . --fix && uv run ruff format .`. Wait for approval before writing tests.

## 3. Tests, in `tests/test_collector_<area>.py`
Use the shared pytest fixtures in `tests/conftest.py` by naming them as test arguments (don't import from `conftest`). Never call the real GitHub or a real LLM in tests.
- `load_fixture(name)`: loads `tests/fixtures/github/<name>` as JSON.
- `fake_conn`: records `(sql, rows)` in `.calls` (and all rows in `.rows`), and fails if a row is missing a `%(name)s` SQL parameter.
- `fake_github(routes)`: each route is `(path, params, page1, page2, ...)`. A request matches only if its params (ignoring `per_page` and `page`) are exactly equal, so list every param the collector must send. Values must be strings. Give 2+ pages to test paging logic.

Write:
- A parse test over every item in the fixture.
- An edge-case test (null user, missing optional field, empty list…).
- A `collect_*` test with `fake_github` + `fake_conn` checking the upsert used, rows, `repo_id` and the returned count.

## 4. Finish
```bash
uv run ruff check . --fix && uv run ruff format .
uv run ruff check . && uv run ruff format --check . && uv run pytest
```
All must pass. Show the user the output of the second command. Then tell the user the exact command to run the collector, and a SQL query to check the new table against the GitHub website. One endpoint per branch and PR.
