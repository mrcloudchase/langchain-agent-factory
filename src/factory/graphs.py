"""One graph for the Agent Server. An assistant with configurable.agent=<name> serves it."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from factory.build import build
from factory.core.spec import load_spec


@lru_cache(maxsize=128)
def _cached(name: str):
    return build(load_spec(name))


def factory(config: dict[str, Any] | None = None):
    name = ((config or {}).get("configurable") or {}).get("agent")
    if not name:
        raise ValueError("factory graph needs configurable.agent = <agent name>")
    return _cached(name)


def forget(name: str | None = None) -> None:
    _cached.cache_clear()
