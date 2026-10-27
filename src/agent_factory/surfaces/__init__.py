"""Surfaces: how a built agent reaches the people who need it.

Every promoted agent is one LangSmith Deployment endpoint that already speaks three
protocols: the Agent Server REST/streaming API, an MCP server at /mcp, and cron/webhook
triggers. A surface in the spec is a declaration of which of those doors to open and
where to point it. The identity rule follows the surface: webhook and cron run as the
org (service identity, tighter tool scoping); Slack, MCP, and chat act for a person.
"""

from __future__ import annotations

import os

from agent_factory.spec import AgentSpec


def deployment_url() -> str:
    return os.environ.get("LANGGRAPH_DEPLOYMENT_URL", "http://localhost:2024").rstrip("/")


def describe_surfaces(spec: AgentSpec) -> list[str]:
    base = deployment_url()
    lines = [
        f"[bold]{spec.display_name}[/bold] ({spec.name}) · identity: "
        f"{'service (unattended)' if spec.is_service_agent else 'user (attended)'}"
    ]
    for s in spec.surfaces:
        if s.kind == "slack":
            lines.append(
                f"  slack    -> channel {s.target}: run `python -m agent_factory.surfaces.slack "
                f"{spec.name}` with SLACK_BOT_TOKEN/SLACK_APP_TOKEN; mentions call assistant "
                f"'{spec.name}' at {base}"
            )
        elif s.kind == "mcp":
            lines.append(
                f"  mcp      -> {base}/mcp exposes tool '{spec.name}' (Streamable HTTP). "
                f"Claude Code: `claude mcp add --transport http {spec.name} {base}/mcp`"
            )
        elif s.kind == "webhook":
            lines.append(
                f"  webhook  -> POST {base}{s.target} (header X-Factory-Secret) starts a run on "
                f"assistant '{spec.name}'; approvals land in the LangSmith Agent Inbox"
            )
        elif s.kind == "cron":
            lines.append(
                f"  cron     -> schedule '{s.schedule}' creates a run with input "
                f"{s.input_template}; register with `factory surfaces register-crons {spec.name}`"
            )
        elif s.kind == "chat":
            lines.append(
                f"  chat     -> any LangGraph-compatible chat UI (e.g. Agent Chat UI) pointed at "
                f"{base} with assistant '{spec.name}'"
            )
        elif s.kind == "sdk":
            lines.append(
                f"  sdk      -> langgraph_sdk.get_client(url='{base}').runs.stream(thread, "
                f"'{spec.name}', input=...)"
            )
    return lines
