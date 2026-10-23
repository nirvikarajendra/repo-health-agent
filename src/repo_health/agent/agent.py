"""Entry point for ADK: it looks for `root_agent` here."""

from repo_health.agent.build import build_agent
from repo_health.config import get_settings

root_agent = build_agent(get_settings().gemini_model)
