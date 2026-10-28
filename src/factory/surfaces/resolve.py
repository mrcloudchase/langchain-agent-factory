"""Map an agent name to an assistant id on the factory graph (what the runs API accepts)."""

from __future__ import annotations

from typing import Any


async def list_assistants(client) -> list[dict[str, Any]]:
    try:
        return await client.assistants.search(limit=200)
    except Exception:  # noqa: BLE001
        return []


def agent_of(assistant: dict[str, Any]) -> str:
    cfg = ((assistant.get("config") or {}).get("configurable") or {}).get("agent")
    return cfg or assistant.get("name") or assistant.get("graph_id") or "?"


async def resolve_assistant(client, name: str) -> str:
    for a in await list_assistants(client):
        if agent_of(a) == name:
            return a["assistant_id"]
    # Not registered yet: register an assistant on the factory graph for this instance.
    a = await client.assistants.create(
        graph_id="factory",
        config={"configurable": {"agent": name}},
        name=name,
        if_exists="do_nothing",
    )
    return a["assistant_id"]
