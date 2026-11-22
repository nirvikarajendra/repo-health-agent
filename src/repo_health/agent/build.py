"""Build the Maintenance Health agent (ADK + Gemini) with its tools."""

from google.adk.agents.llm_agent import Agent

from repo_health.agent.tools import (
    get_bug_close_rate,
    get_contributor_stats,
    get_first_response_time,
    get_pr_review_time,
    get_release_cadence,
    get_repo_overview,
    list_repos,
)

TOOLS = [
    list_repos,
    get_repo_overview,
    get_first_response_time,
    get_bug_close_rate,
    get_pr_review_time,
    get_release_cadence,
    get_contributor_stats,
]

INSTRUCTION = """\
You answer questions about how well open-source GitHub repositories are maintained.

- Answer only from tool results; never estimate or invent numbers.
- Always state the data_as_of date of the data you used.
- When you can't answer, say "I don't know" and why:
  - the repo is not tracked: say so and list the tracked repos (tracked_repos in the
    tool's error result);
  - no tool covers the question: say so.
- For "is X healthy" or "is X well maintained": call get_repo_overview and every metric
  tool (first response time, bug close rate, PR review time, release cadence, contributor
  stats), then summarise each in one line with its data_as_of. Give no overall score.
- Always include every item in warnings, and up to 3 links from *_urls when you mention
  unanswered or unreviewed items. Never build links yourself.
- Write dates as YYYY-MM-DD.
- Never describe your reasoning or what you are about to do; give only the answer.
"""


def build_agent(model: str | None) -> Agent:
    """Return the agent using Gemini `model` (from the GEMINI_MODEL setting)."""
    if not model:
        raise ValueError("GEMINI_MODEL is not set: add the Gemini model name to .env")
    return Agent(
        name="repo_health_agent",
        model=model,
        description="Answers questions about a GitHub repo's maintenance, from collected data.",
        instruction=INSTRUCTION,
        tools=TOOLS,
    )
