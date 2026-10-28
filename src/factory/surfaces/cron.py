"""Cron surface: scheduled runs registered on the Agent Server through the LangGraph SDK."""

from __future__ import annotations

from factory.core.spec import AgentSpec
from factory.surfaces import deployment_url


def register_crons(spec: AgentSpec, *, url: str | None = None, dry_run: bool = False, client=None):
    lines = []
    crons = [s for s in spec.surfaces if s.kind == "cron"]
    if not crons:
        return [f"{spec.name}: no cron surfaces"]
    if client is None and not dry_run:
        from langgraph_sdk import get_sync_client

        client = get_sync_client(url=url or deployment_url())
    for s in crons:
        question = (s.input_template or {}).get("question", "Run your scheduled task")
        payload = {"messages": [{"role": "user", "content": question}]}
        if dry_run:
            lines.append(f"{spec.name}: would register '{s.schedule}' -> {payload}")
            continue
        cron = client.crons.create(
            spec.name, schedule=s.schedule, input=payload, metadata={"surface": "cron"}
        )
        lines.append(f"{spec.name}: registered cron {cron.get('cron_id', cron)} ({s.schedule})")
    return lines
