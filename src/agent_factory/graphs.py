"""Graph entry points for LangSmith Deployment / `langgraph dev`.

Every agent in agents/ is built from its spec at import time. Checkpointer and store are
left to the platform, which provisions them. Offline mode still works here, so
`langgraph dev` runs without model keys for demos.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from agent_factory.harness import build_agent
from agent_factory.spec import load_spec


def _make(name: str):
    return build_agent(load_spec(name))


@lru_cache(maxsize=64)
def _cached(name: str):
    return _make(name)


def factory(config: dict[str, Any] | None = None):
    """Generic graph: serves any spec by name, so agents created at runtime need no restart.

    An assistant on the Agent Server points at this graph with
    `config={"configurable": {"agent": "<name>"}}`. One graph, many assistants, each a spec.
    """
    name = ((config or {}).get("configurable") or {}).get("agent")
    if not name:
        raise ValueError("factory graph needs configurable.agent = <agent name>")
    return _cached(name)


def forget(name: str) -> None:
    """Drop a cached build after its spec changed."""
    _cached.cache_clear()


research_digest = _make("research_digest")
support_triage = _make("support_triage")
engineering_assistant = _make("engineering_assistant")

__all__ = ["engineering_assistant", "factory", "research_digest", "support_triage"]
