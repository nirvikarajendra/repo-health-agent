# Metric definitions

Exact definitions for the metric tools. Code follows these; if one is unclear, ask, don't guess.

## Shared rules
- **Window:** every tool takes `days` and covers `(data_as_of - days, data_as_of]`. It ends at `data_as_of`, not `now()`, so the same data always gives the same answer. Ignore rows after `data_as_of`. `days` must be 1–365 (the collector keeps 365 days); check it in Python before running the SQL and raise `ValueError` otherwise.
- **No complete snapshot:** if `data_as_of` is NULL, return the model with every number `None` and `note = "no complete snapshot"`. An unknown repo returns `None` (no model).
- **Maintainer:** `author_association IN ('OWNER', 'MEMBER', 'COLLABORATOR')`.
- **Bot:** a login ending in `[bot]`, or `Copilot` (no suffix). Bots are ignored everywhere: as authors, commenters, reviewers and committers.
- **Deleted users:** a NULL login (a deleted "ghost" account) counts as a person: not a bot and not a maintainer. Compare logins with `IS DISTINCT FROM` (never `<>` or a bare `NOT LIKE`), so NULL rows are never dropped silently. (Commits are the exception: see `get_contributor_stats`.)
- **Issues vs PRs:** the `issues` table holds both. Issue metrics use `is_pull_request = false`.
- **Times:** report the median (`percentile_cont(0.5)`), in hours unless stated, never the mean. The median covers only items that got a response or review; the count of those that didn't is reported beside it.
- **Counts behind a number:** report how many items the number is based on, so "median 2 h" over 1 issue is visible as such.

## get_first_response_time (default `days` = 90)
- **Issues:** non-PR issues created in the window whose author is not a maintainer and not a bot.
- **Response:** the earliest comment (`comments.created_at` ≤ `data_as_of`) by a maintainer who is not a bot and not the issue's author.
- **Result:** median hours from issue creation to that comment; the number of issues counted; the number with no response.
- **Unanswered issues:** the numbers of the first 10 (oldest first), and how many were, at `data_as_of`: closed as completed (`state_reason` `completed` or NULL), closed as not planned (`not_planned` or `duplicate`), or still open (including issues closed after `data_as_of`). The three counts add up to the number with no response.
- **Note:** "Only issues are counted; Discussions are not included." (unless there is no complete snapshot).
- Discussions are not counted; repos that answer in Discussions will look less responsive. Possible later: collect discussions and what closed each issue via GraphQL.
- unanswered_closed_completed may include issues that were converted to Discussions (GitHub keeps them as closed/completed).
- The state at `data_as_of` is worked out from the issue's current state, `state_reason` and `closed_at` (no history is stored), so an issue reopened or closed again after `data_as_of` can land in the wrong group. Possibly fixed later by GraphQL issue events.

## get_bug_close_rate (default `days` = 365)
- **Bug:** a non-PR issue with a label matching `\mbug\M` and not matching `\mnot[\s_-]+a[\s_-]+bug\M`, both ignoring case (`bug`, `Bug`, `type: bug`, `kind/bug`; not `debug`, `Question/Not a bug`, `not-a-bug` or `Not_A_Bug`), whose author is not a bot. The same label rule (bots included) decides "Not labelled" and `labelled_bug_issues`, counting only issues created on or before `data_as_of`.
- **Not labelled:** if no issue of the repo has a bug label, return rate and counts `None` with `note = "not labelled"`, never 0%.
- **`days`:** must be 31–365 (the window `(data_as_of - days, data_as_of - 30 days]` is empty for 30 or less); raise `ValueError` otherwise.
- **Bugs counted:** created in the window **and** at least 30 days before `data_as_of`, so each had its full 30 days. Leave out bugs closed as `not_planned` or `duplicate` on or before `data_as_of` entirely (not in the count). A bug still open at `data_as_of` counts as not fixed, whatever happened to it later.
- **Fixed:** `state = 'closed'` and `state_reason` is `completed` or NULL, closed within 30 days of creation and on or before `data_as_of`.
- **Result:** fixed ÷ counted (0–1); the number counted; the number fixed; the numbers of the first 10 counted but not fixed (oldest first); `labelled_bug_issues` (0 when not labelled): Non-PR issues with a bug label among stored issues (all open issues plus those updated in the last 365 days). Very low values mean the repo rarely labels bugs, so the rate is not reliable. Labelled but nothing counted: rate `None`, counts 0, no note.
- A bug converted to a Discussion counts as fixed (GitHub keeps it as closed/completed).
- Labels are the current ones, not those at `data_as_of`: a label added or removed later is seen as it is now.

## get_pr_review_time (default `days` = 90)
- **PRs:** issues with `is_pull_request = true` joined to `pull_requests`, `is_draft = false`, created in the window, whose author is not a maintainer and not a bot (like first response time: it measures how outside contributions are handled).
- **Drafts:** `is_draft` is the state when collected, so PRs still in draft are left out, and a PR that started as a draft is timed from its creation, not from when it was marked ready (GitHub's data doesn't give that time cheaply). This can make the median longer than the real wait.
- **First review:** the earliest review per PR by `submitted_at` (not NULL, ≤ `data_as_of`), in any state (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`), by a maintainer who is not a bot and not the PR's author (no self-reviews). Plain comments on a PR are not reviews.
- **Result:** median hours from PR creation to the first review; the number of PRs counted; the number with no review.
- **Unreviewed PRs:** the numbers of the first 10 (oldest first), and how many were, at `data_as_of`: merged (`merged_at` ≤ `data_as_of`), closed without merging (closed on or before `data_as_of`), or still open (including PRs merged or closed after `data_as_of`). The three counts add up to the number with no review.
- **Note:** only "no complete snapshot".

## get_release_cadence (all collected releases; no `days`)
- **Releases:** `published_at` not NULL and ≤ `data_as_of`, `is_draft = false`, `is_prerelease = false`. Ordered by `published_at` (then `id`), never by tag.
- **Result:** the latest release's tag and date; days from it to `data_as_of`; the median gap in days between consecutive releases among the **last 5** (so up to 4 gaps), with the number of gaps and the 5 tags (oldest first); the number of releases; releases in `(data_as_of - 365 days, data_as_of]`. Days are unrounded floats.
- **Bursts:** a few quick patch releases make the median gap short; `days_since_latest_release` and `releases_last_365_days` are the steadier signals.
- **Edge cases:** no releases → derived values `None`, counts 0, tags `[]`, `note = "no GitHub releases"`; one release → gap `None`, 0 gaps.
- Projects that only push git tags or publish to PyPI without GitHub Releases show "no GitHub releases" even though they do release.

## get_contributor_stats (default `days` = 365)
- **Commits:** `commits` with `committed_at` in the window. These are always "merged to the default branch": the collector reads only the default branch's history. Never add commits from other branches.
- **Active contributors:** distinct non-bot `author_login`.
- **Concentration:** the smallest number of authors who together made at least 50% of the non-bot, attributed commits (1 means one person carries the project).
- **Unattributed:** commits with a NULL `author_login` are not dropped silently: report their count separately (they're left out of the two numbers above).
- **Result:** active contributors; concentration; counted commits; unattributed commits.
