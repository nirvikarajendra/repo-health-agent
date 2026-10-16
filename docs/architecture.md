# Architecture

## Purpose
Help developers decide whether an open-source library is well maintained, using real GitHub activity instead of star counts.

## What it does
- Gives a repo overview: stars, forks, language, licence, open issues, contributors, last release.
- Answers maintenance questions such as how fast maintainers respond to issues, how many bugs get closed, how long PRs wait for review, and how often releases ship.
- Gives a short health summary built only from those numbers, with the snapshot date.
- Says "I don't know" when a question is outside its data.

## What it doesn't do
- Read or summarise issue, PR or README text
- Judge code quality or security
- Predict a project's future or rank maintainers
- Work on private repos or live data
- Write anything to GitHub

## How it works
```
GitHub REST API ──► Collector ──► Postgres ──► Metric tools ──► Agent ──► User
                    (script)     (snapshot)    (read-only)
```
- **Collector:** a plain script that copies public repo data from GitHub into Postgres.
- **Postgres:** holds a snapshot of the tracked repos. The agent only ever reads from here.
- **Metric tools:** one function per metric. Each runs a fixed, read-only query.
- **Agent:** understands the question, calls the right tools, and writes the answer from their results.

## Agent and tools
One agent: the **Maintenance Health agent**.

| Tool | Answers |
|---|---|
| `list_repos` | which repos are tracked, and the snapshot date |
| `get_repo_overview` | general repo stats |
| `get_first_response_time` | how fast maintainers reply to new issues |
| `get_bug_close_rate` | share of bugs closed within 30 days |
| `get_pr_review_time` | how long PRs wait for a first review |
| `get_release_cadence` | time since the last release and the usual gap between releases |
| `get_contributor_stats` | active contributors, and how concentrated the work is |

## Tech stack
Python · Google ADK + Gemini (free tier) · Postgres · Docker Compose · GitHub Actions
