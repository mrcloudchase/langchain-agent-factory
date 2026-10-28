"""Webhook surface: a FastAPI app mounted into the Agent Server via `http.app` in langgraph.json.

External systems (a helpdesk, a CI system) POST events here. The route verifies a shared
secret *before* anything else, maps the event to the agent's declared input template,
and starts a run on the local Agent Server through the LangGraph SDK. Sensitive tools
still pause for approval; nobody gets a refund because a webhook fired.
"""

from __future__ import annotations

import hmac
import os
import uuid
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from agent_factory.spec import AgentSpec, list_specs
from agent_factory.surfaces import deployment_url

app = FastAPI(title="Agent Factory surfaces")

from agent_factory.surfaces.console import router as console_router  # noqa: E402

app.include_router(console_router)


def _secret() -> str:
    return os.environ.get("HELPDESK_WEBHOOK_SECRET", "")


def verify_secret(provided: str | None) -> None:
    expected = _secret()
    if not expected or provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="bad or missing X-Factory-Secret")


@lru_cache(maxsize=1)
def webhook_routes() -> dict[str, tuple[AgentSpec, dict[str, Any]]]:
    """Route table from the specs. Cached: the Agent Server forbids disk reads in handlers."""
    routes = {}
    for spec in list_specs():
        for s in spec.surfaces:
            if s.kind == "webhook" and s.target:
                routes[s.target] = (spec, s.input_template or {"question": "{event}"})
    return routes


def render_input(template: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in template.items():
        if isinstance(v, str):
            try:
                out[k] = v.format(**{**event, "event": event})
            except (KeyError, IndexError):
                out[k] = v
        else:
            out[k] = v
    return out


async def start_run(
    assistant_id: str, inputs: dict[str, Any], *, client=None, base_url: str | None = None
) -> dict[str, Any]:
    """Create a thread and a background run on the Agent Server. Injectable for tests.

    Uses the async SDK client: the route runs inside the server's event loop, so a
    blocking HTTP call here would stall every other request. The app is mounted inside
    the Agent Server, so it addresses itself via the request's base URL.
    """
    if client is None:
        from langgraph_sdk import get_client

        client = get_client(url=base_url or deployment_url())
    thread = await client.threads.create()
    question = inputs.get("question", "")
    run = await client.runs.create(
        thread["thread_id"],
        assistant_id,
        input={"messages": [{"role": "user", "content": question}]},
        metadata={"surface": "webhook"},
    )
    return {"thread_id": thread["thread_id"], "run_id": run["run_id"], "assistant_id": assistant_id}


@app.get("/webhooks/health")
def health() -> dict[str, Any]:
    return {"ok": True, "routes": sorted(webhook_routes())}


@app.post("/webhooks/{name}")
async def receive(
    name: str,
    request: Request,
    x_factory_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_factory_secret)  # auth first, always
    route = f"/webhooks/{name}"
    routes = webhook_routes()
    if route not in routes:
        raise HTTPException(status_code=404, detail=f"no agent declares surface {route}")
    spec, template = routes[route]
    event = await request.json()
    inputs = render_input(template, event)
    client = getattr(request.app.state, "sdk_client", None)
    base_url = str(request.base_url).rstrip("/")
    result = await start_run(spec.name, inputs, client=client, base_url=base_url)
    result["event_id"] = event.get("id", str(uuid.uuid4()))
    return result


# Warm the route cache at import, outside any request handler.
webhook_routes()
