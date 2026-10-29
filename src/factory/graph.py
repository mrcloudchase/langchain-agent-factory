"""The one graph registered with the Agent Server.

Every agent is an assistant on this graph with `configurable.agent=<name>`. Builds are cached
per agent and rebuilt when the agent's file changes, so reconfiguring needs no restart.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from factory.agents import store
from factory.build import build
from factory.spec import load_spec


@lru_cache(maxsize=64)
def _built(name: str, version: int):
    return build(load_spec(name))


def factory(config: dict[str, Any]):
    name = (config.get("configurable") or {}).get("agent")
    if not name:
        raise ValueError("set configurable.agent to the agent's name")
    return _built(name, (store().directory(name) / "agent.yaml").stat().st_mtime_ns)
