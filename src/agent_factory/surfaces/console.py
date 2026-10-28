"""The platform-team console, served inside the Agent Server at /console.

It is deliberately not a rebuild of LangSmith Studio or the Agent Inbox. It shows the
things the factory owns: the catalog, pending approvals across every agent, the gate,
promotion, and the ledger, and links out to LangSmith for traces and experiments.
Handlers never block the event loop: disk and model work run in threads, and the
Agent Server is addressed through the async SDK at the request's own base URL.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter(prefix="/console", tags=["console"])
PAGE = (Path(__file__).parent / "console.html").read_text()


def _sdk(request: Request):
    client = getattr(request.app.state, "sdk_client", None)
    if client is not None:
        return client
    from langgraph_sdk import get_client

    return get_client(url=str(request.base_url).rstrip("/"))


def _catalog_sync() -> dict[str, Any]:
    from agent_factory.catalog import build_catalog

    return build_catalog()


def _mode_sync() -> dict[str, Any]:
    from agent_factory.models import is_offline
    from agent_factory.registry import load_registry

    reg = load_registry()
    tier = reg.model_tier(reg.default_model_tier)
    return {
        "offline": is_offline(tier.model if tier else None),
        "model": tier.model if tier else None,
        "langsmith": bool(os.environ.get("LANGSMITH_API_KEY")),
        "project": os.environ.get("LANGSMITH_PROJECT", "agent-factory"),
    }


def _parse_interrupts(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull pending action requests out of a thread state, whatever shape the server used."""
    found: list[dict[str, Any]] = []
    for task in state.get("tasks") or []:
        for intr in task.get("interrupts") or []:
            value = intr.get("value") if isinstance(intr, dict) else getattr(intr, "value", None)
            if isinstance(value, dict) and value.get("action_requests"):
                found.append(value)
    values = state.get("values") or {}
    for intr in values.get("__interrupt__") or []:
        value = intr.get("value") if isinstance(intr, dict) else None
        if isinstance(value, dict) and value.get("action_requests"):
            found.append(value)
    return found


async def _pending_approvals(client) -> list[dict[str, Any]]:
    threads = await client.threads.search(status="interrupted", limit=50)
    pending = []
    for th in threads:
        state = await client.threads.get_state(th["thread_id"])
        meta = th.get("metadata") or {}
        agent = meta.get("graph_id") or meta.get("assistant_id") or "?"
        for value in _parse_interrupts(state):
            configs = {c["action_name"]: c for c in value.get("review_configs", [])}
            for req in value["action_requests"]:
                pending.append(
                    {
                        "thread_id": th["thread_id"],
                        "agent": agent,
                        "tool": req["name"],
                        "args": req.get("args", {}),
                        "allowed": configs.get(req["name"], {}).get(
                            "allowed_decisions", ["approve", "reject"]
                        ),
                        "surface": meta.get("surface"),
                        "updated_at": th.get("updated_at"),
                    }
                )
    return pending


async def _recent_threads(client, limit: int = 12) -> list[dict[str, Any]]:
    threads = await client.threads.search(limit=limit)
    out = []
    for th in threads:
        meta = th.get("metadata") or {}
        values = th.get("values") or {}
        msgs = values.get("messages") or []
        last = msgs[-1] if msgs else {}
        first_human = next((m for m in msgs if m.get("type") == "human"), {})
        out.append(
            {
                "thread_id": th["thread_id"],
                "agent": meta.get("graph_id") or meta.get("assistant_id") or "?",
                "status": th.get("status"),
                "surface": meta.get("surface") or "console",
                "question": _text(first_human.get("content"))[:120],
                "last": _text(last.get("content"))[:240],
                "tools": [m.get("name") for m in msgs if m.get("type") == "tool"],
                "updated_at": th.get("updated_at"),
            }
        )
    return out


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return "" if content is None else str(content)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def page() -> str:
    return PAGE


@router.get("/api/state")
async def state(request: Request) -> dict[str, Any]:
    client = _sdk(request)
    catalog, mode = await asyncio.gather(
        asyncio.to_thread(_catalog_sync), asyncio.to_thread(_mode_sync)
    )
    try:
        pending, recent = await asyncio.gather(_pending_approvals(client), _recent_threads(client))
        server_ok = True
    except Exception as e:  # noqa: BLE001
        pending, recent, server_ok = [], [], False
        mode["server_error"] = repr(e)[:200]
    return {
        "mode": mode,
        "server_ok": server_ok,
        "agents": catalog["agents"],
        "teams": catalog["teams"],
        "pending": pending,
        "recent": recent,
    }


class RunRequest(BaseModel):
    agent: str
    question: str


@router.post("/api/run")
async def run(body: RunRequest, request: Request) -> dict[str, Any]:
    client = _sdk(request)
    thread = await client.threads.create(metadata={"surface": "console"})
    run = await client.runs.create(
        thread["thread_id"],
        body.agent,
        input={"messages": [{"role": "user", "content": body.question}]},
        metadata={"surface": "console"},
    )
    return {"thread_id": thread["thread_id"], "run_id": run["run_id"]}


class Decision(BaseModel):
    decision: str  # approve | reject
    message: str | None = None


@router.post("/api/approvals/{thread_id}")
async def decide(thread_id: str, body: Decision, request: Request) -> dict[str, Any]:
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    client = _sdk(request)
    thread = await client.threads.get(thread_id)
    meta = thread.get("metadata") or {}
    agent = meta.get("graph_id") or meta.get("assistant_id")
    if not agent:
        raise HTTPException(404, "thread has no agent")
    state = await client.threads.get_state(thread_id)
    n = sum(len(v["action_requests"]) for v in _parse_interrupts(state)) or 1
    decision = (
        {"type": "approve"}
        if body.decision == "approve"
        else {"type": "reject", "message": body.message or "Rejected by operator in the console."}
    )
    run = await client.runs.create(
        thread_id,
        agent,
        command={"resume": {"decisions": [decision] * n}},
        metadata={"surface": "console", "decision": body.decision},
    )
    return {"thread_id": thread_id, "run_id": run["run_id"], "decision": body.decision, "count": n}


@router.get("/api/threads/{thread_id}")
async def thread_detail(thread_id: str, request: Request) -> dict[str, Any]:
    client = _sdk(request)
    state = await client.threads.get_state(thread_id)
    msgs = (state.get("values") or {}).get("messages") or []
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "type": m.get("type"),
                "name": m.get("name"),
                "content": _text(m.get("content"))[:1200],
                "tool_calls": [tc.get("name") for tc in (m.get("tool_calls") or [])],
            }
            for m in msgs
        ],
        "pending": _parse_interrupts(state),
    }


class GateRequest(BaseModel):
    agent: str


@router.post("/api/gate")
async def gate(body: GateRequest) -> dict[str, Any]:
    from agent_factory.evals import run_gate
    from agent_factory.spec import load_spec

    try:
        spec = await asyncio.to_thread(load_spec, body.agent)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    report = await asyncio.to_thread(run_gate, spec)
    return report.to_dict()


class PromoteRequest(BaseModel):
    agent: str
    to: str


@router.post("/api/promote")
async def promote_agent(body: PromoteRequest) -> dict[str, Any]:
    from agent_factory.promote import PromotionBlocked, promote
    from agent_factory.spec import load_spec

    if body.to not in ("staging", "production"):
        raise HTTPException(400, "to must be staging or production")
    spec = await asyncio.to_thread(load_spec, body.agent)
    try:
        res = await asyncio.to_thread(promote, spec, body.to)
    except PromotionBlocked as e:
        return {"ok": False, "blocked": str(e), "report": e.report.to_dict() if e.report else None}
    return {
        "ok": True,
        "stage": res.stage,
        "notes": res.notes,
        "context_hub_url": res.context_hub_url,
        "report": res.report.to_dict() if res.report else None,
    }
