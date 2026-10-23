"""Build the Maintenance Health agent (ADK + Gemini) with its tools."""

from google.adk.agents.llm_agent import Agent

from repo_health.agent.tools import get_repo_overview, list_repos

INSTRUCTION = """\
You answer questions about how well open-source GitHub repositories are maintained.
Answer only from tool results. Never estimate or invent numbers.
Always state the data_as_of date of the data you used.
If no tool covers the question, say "I don't know".
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
        tools=[list_repos, get_repo_overview],
    )
