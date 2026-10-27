"""Graph entry points for LangSmith Deployment / `langgraph dev`.

Every agent in agents/ is built from its spec at import time. Checkpointer and store are
left to the platform, which provisions them. Offline mode still works here, so
`langgraph dev` runs without model keys for demos.
"""

from __future__ import annotations

from agent_factory.harness import build_agent
from agent_factory.spec import load_spec


def _make(name: str):
    return build_agent(load_spec(name))


research_digest = _make("research_digest")
support_triage = _make("support_triage")
engineering_assistant = _make("engineering_assistant")

__all__ = ["engineering_assistant", "research_digest", "support_triage"]
