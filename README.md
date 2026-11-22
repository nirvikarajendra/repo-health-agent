# repo-health-agent
AI agent (Google ADK + Gemini) that answers "Is this open-source library well maintained?" from a Postgres snapshot of GitHub data. Every number comes from a fixed SQL metric, never from the LLM.

Planned after v1: an issue-summariser agent (RAG over issue text with pgvector) and a dependency-security agent, making it multi-agent.

## Try it

**Prerequisites:** Python 3.12 + [uv](https://docs.astral.sh/uv/), Docker (Compose v2), a GitHub token (fine-grained, read-only, public repos), a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

Run every command from the repo root (that's where `.env` is read from).

```bash
git clone https://github.com/nirvikarajendra/repo-health-agent.git
cd repo-health-agent
cp .env.example .env    # set POSTGRES_PASSWORD (same in DATABASE_URL), GITHUB_TOKEN, GOOGLE_API_KEY
docker compose up -d
uv run python -m repo_health.migrate
uv run python -m repo_health.collector encode/httpx
```

Any public repo works, e.g. fastapi/fastapi (slower, ~2,000 requests).

**Run the agent:**

```bash
uv run adk web src/repo_health --port 8000   # browser: http://localhost:8000, pick "agent"
uv run adk run src/repo_health/agent         # terminal
```

**Example:** "Is fastapi/fastapi healthy?" (2026-11-22)

> * Overview: FastAPI framework, high performance, easy to learn, fast to code, ready for production (105,057 stars, 49 open issues, data as of 2026-11-22).
> * First response time: No median hours because none of the 11 counted issues got a maintainer comment (data as of 2026-11-22). Unanswered issues include https://github.com/fastapi/fastapi/issues/16244, https://github.com/fastapi/fastapi/issues/16253, https://github.com/fastapi/fastapi/issues/16254. Warnings: Only issues are counted; Discussions are not included., no median: none of the 11 counted issues got a maintainer comment.
> * Bug close rate: 100% of 13 counted bugs closed as completed within 30 days (data as of 2026-11-22). Warnings: only 26 stored issues are bug-labelled; rate may not be reliable.
> * PR review time: Median 30.0 hours to first formal maintainer review across reviewed PRs, with 131 counted and 130 without review (data as of 2026-11-22). Unreviewed PRs include https://github.com/fastapi/fastapi/pull/16243, https://github.com/fastapi/fastapi/pull/16245, https://github.com/fastapi/fastapi/pull/16248. Warnings: median based on 1 reviewed PR (131 counted), Of the 130 PRs without a maintainer review: 0 were merged, 122 were closed without merging, 8 are still open.
> * Release cadence: Latest release tag 0.165.0 published on 2026-11-18, with 129 releases in the last 365 days and a median gap of 0.7 days (data as of 2026-11-22). Warnings: median gap based on a burst: 5 releases within 4.1 days, Days since the latest release are counted up to the data date (data_as_of), not today.
> * Contributor stats: 64 active contributors made 751 commits in the last 365 days, with 1 author responsible for half of the commits (data as of 2026-11-22). Warnings: none.

**Limits**
- Answers only from the 7 tools; anything else gets "I don't know".
- GitHub Discussions are not counted.
- Data is as fresh as the last collector run (`data_as_of` in every answer).
