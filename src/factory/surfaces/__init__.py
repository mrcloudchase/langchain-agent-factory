"""Surfaces: how a built agent reaches the people who need it. One deployed endpoint, many doors."""

from __future__ import annotations

import os

from factory.core.spec import AgentSpec


def deployment_url() -> str:
    return os.environ.get("LANGGRAPH_DEPLOYMENT_URL", "http://localhost:2024").rstrip("/")


def describe_surfaces(spec: AgentSpec) -> list[dict]:
    base = deployment_url()
    out = []
    for s in spec.surfaces:
        if s.kind == "slack":
            how = (
                f"Slack bot for channel {s.target}: `python -m factory.surfaces.slack {spec.name}` with "
                f"SLACK_BOT_TOKEN/SLACK_APP_TOKEN. Mentions run assistant '{spec.name}' at {base}."
            )
        elif s.kind == "mcp":
            how = (
                f"{base}/mcp exposes tool '{spec.name}' (Streamable HTTP). Claude Code: "
                f"`claude mcp add --transport http {spec.name} {base}/mcp`"
            )
        elif s.kind == "webhook":
            how = (
                f"POST {base}{s.target} with header X-Factory-Secret starts a run; approvals land in "
                f"the console and the LangSmith Agent Inbox."
            )
        elif s.kind == "cron":
            how = f"Schedule '{s.schedule}' creates a run with {s.input_template}; register with `factory surfaces register-crons {spec.name}`."
        elif s.kind == "chat":
            how = f"Any LangGraph-compatible chat UI (Studio, Agent Chat UI) pointed at {base}, assistant '{spec.name}'."
        else:
            how = f"langgraph_sdk.get_client(url='{base}').runs.stream(thread, '{spec.name}', input=...)"
        out.append(
            {
                "kind": s.kind,
                "target": s.target,
                "schedule": s.schedule,
                "identity": "service (unattended)"
                if s.kind in ("webhook", "cron")
                else "user (attended)",
                "how": how,
            }
        )
    return out
