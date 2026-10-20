# Fields per endpoint

Store only these fields. The table in `sql/migrations/` wins if it disagrees: tell the user.

| Endpoint (under `/repos/{owner}/{repo}/`) | Fields → column | How to limit |
|---|---|---|
| `pulls` | `number`, `draft`→`is_draft`, `base.ref`→`base_ref`, `merged_at` | All `state=open`, plus `state=closed&sort=updated&direction=desc`: skip items whose `updated_at` is older than `since`, then stop paging. |
| `pulls/{number}/reviews` | `id`, PR number from the request→`pr_number`, `user.login`→`reviewer_login`, `author_association`, `state`, `submitted_at` | One call per PR: agree the design with the user first. |
| `releases` | `id`, `tag_name`→`tag`, `prerelease`→`is_prerelease`, `draft`→`is_draft`, `published_at` | Fetch all (small). |
| `commits` | `sha`, `author.login`→`author_login`, `commit.committer.date`→`committed_at` | `since` (it filters on the committer date). `author` can be `null`. |
