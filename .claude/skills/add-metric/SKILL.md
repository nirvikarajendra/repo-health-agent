---
name: add-metric
description: Add one maintenance metric tool to repo_health.metrics (fixed SQL → Pydantic model, tested against the real test database). Use when asked for first response time, bug close rate, PR review time, release cadence or contributor stats.
argument-hint: "<metric, e.g. first response time>"
---

# Add a metric: $ARGUMENTS

Copy the shape of `src/repo_health/metrics/list_repos.py` and `repo_overview.py`. Stop at each **Checkpoint** and wait for the user. If no metric is given, ask which one.

## 1. Plan
Read the metric and the shared rules in [definitions.md](definitions.md), and the columns in `sql/migrations/`. List every edge case (no data, all bots, nothing in the window, NULL `data_as_of`, boundary dates).

**Checkpoint:** show the definition, the edge cases and the model's fields.

## 2. SQL + model
In `metrics/<name>.py`: one fixed parameterised `SELECT` (`%(repo)s`, `%(days)s`; no string formatting) that joins `repo_data_as_of` and matches the name like `repo_overview.py` (ignoring case, newest snapshot wins). In `models.py`: one model per tool with named fields, `data_as_of` (reuse `DATA_AS_OF`) and `note: str | None`. Add `Field(description=...)` on any number whose meaning isn't obvious (unit, window, what's counted). Unknown repo → `None`.

**Checkpoint:** show the code.

## 3. Tests
In `tests/test_metrics_<name>.py`, use `db_conn` and `repo_id` from `conftest.py`, and insert rows with plain parameterised SQL. One test per edge case from step 1, with expected values worked out by hand in a comment. Then one mutation check: back up the file to the scratchpad, break one rule (e.g. drop the bot filter), show a test failing, restore it and confirm with `diff`.

**Checkpoint:** show the tests and the mutation check output.

## 4. Finish
Run `uv run ruff format . && uv run ruff check . && uv run pytest` and show the output. Run the tool on `encode/httpx` against the real database and show the result. Update the `metrics/` line in `CLAUDE.md` and `docs/development.md`.

**Checkpoint:** show the output and the doc lines.
