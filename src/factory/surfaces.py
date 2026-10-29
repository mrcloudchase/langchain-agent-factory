"""Surfaces: where an agent is reachable. One Agent Server, several doors."""

from __future__ import annotations

from factory.spec import Spec
from factory.templates import UNATTENDED_SURFACES

_HOW = {
    "chat": "Console Try it, LangSmith Studio, or Agent Chat UI with assistant '{name}'.",
    "sdk": "langgraph_sdk.get_client(url=SERVER).runs.wait(thread, ASSISTANT_ID, input=...)",
    "mcp": "MCP tool at SERVER/mcp. Claude Code: claude mcp add --transport http {name} SERVER/mcp",
    "webhook": 'POST SERVER/webhooks/{name}, header X-Factory-Secret, JSON {{"question": ...}}.',
    "cron": "Runs '{question}' on schedule '{schedule}'. Register with: factory schedule {name}",
}


def describe(spec: Spec) -> list[dict[str, str]]:
    values = {
        "name": spec.name,
        "schedule": spec.cron.schedule if spec.cron else "",
        "question": spec.cron.question if spec.cron else "",
    }
    return [
        {
            "kind": s,
            "identity": "unattended" if s in UNATTENDED_SURFACES else "a person",
            "how": _HOW[s].format(**values),
        }
        for s in spec.surfaces
    ]
