# Fields per endpoint

Which metric tool needs each endpoint (see `docs/architecture.md`), and the only fields to store.

| Endpoint | Metric tool | Fields → column | Limiting the data |
|---|---|---|---|
| `/repos/{owner}/{repo}/pulls` | `get_pr_review_time` | `number`, `draft`→`is_draft`, `merged_at`, `base.ref`→`base_ref` (dates, author and state already come from the `issues` table, since every PR is also an issue) | No `since`. Fetch all `state=open`, plus `state=closed&sort=updated&direction=desc`, stopping once `updated_at` is older than `since`. Table `pull_requests` exists. |
| `/repos/{owner}/{repo}/pulls/{number}/reviews` | `get_pr_review_time` | `id`, `user.login`→`reviewer_login`, `author_association`, `state`, `submitted_at` (null while pending) | One call per PR, so only for PRs saved in this run. |
| `/repos/{owner}/{repo}/releases` | `get_release_cadence` | `id`, `tag_name`→`tag`, `prerelease`→`is_prerelease`, `draft`→`is_draft`, `published_at` | No `since`, but small: fetch all. |
| `/repos/{owner}/{repo}/commits` | `get_contributor_stats` | `sha`, `author.login` (GitHub account, can be `null`), `commit.author.date`→`committed_at` | Supports `since`. Don't confuse `author` (GitHub account) with `commit.author` (git name/email). |

Always check the real column names in `sql/migrations/` before writing the upsert. Every `NOT NULL` column must get a value. If this table and a migration disagree, the migration wins: tell the user.
