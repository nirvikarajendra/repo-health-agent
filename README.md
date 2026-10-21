# repo-health-agent
AI agent (Google ADK + Gemini) that answers "Is this open-source library well maintained?" from a Postgres snapshot of GitHub data. Every number comes from a fixed SQL metric, never from the LLM.

Planned after v1: an issue-summariser agent (RAG over issue text with pgvector) and a dependency-security agent, making it multi-agent.
