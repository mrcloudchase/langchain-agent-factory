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


async def _assistants(client) -> list[dict[str, Any]]:
    try:
        return await client.assistants.search(limit=200)
    except Exception:  # noqa: BLE001
        return []


def _agent_of(assistant: dict[str, Any]) -> str:
    """The factory agent name an assistant serves: its graph, or configurable.agent."""
    cfg = ((assistant.get("config") or {}).get("configurable") or {}).get("agent")
    return cfg or assistant.get("graph_id") or assistant.get("name") or "?"


async def _resolve_assistant(client, name: str) -> str:
    """Map an agent name to something runs.create accepts: a graph id or an assistant id."""
    for a in await _assistants(client):
        if a.get("graph_id") == name:
            return name
    for a in await _assistants(client):
        if _agent_of(a) == name or a.get("name") == name:
            return a["assistant_id"]
    return name


def _thread_agent(meta: dict[str, Any], amap: dict[str, str]) -> str:
    gid = meta.get("graph_id")
    if gid and gid != "factory":
        return gid
    return amap.get(meta.get("assistant_id", ""), gid or "?")


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


async def _pending_approvals(client, amap: dict[str, str]) -> list[dict[str, Any]]:
    threads = await client.threads.search(status="interrupted", limit=50)
    pending = []
    for th in threads:
        state = await client.threads.get_state(th["thread_id"])
        meta = th.get("metadata") or {}
        agent = _thread_agent(meta, amap)
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


async def _recent_threads(client, amap: dict[str, str], limit: int = 12) -> list[dict[str, Any]]:
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
                "agent": _thread_agent(meta, amap),
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
        amap = {a["assistant_id"]: _agent_of(a) for a in await _assistants(client)}
        pending, recent = await asyncio.gather(
            _pending_approvals(client, amap), _recent_threads(client, amap)
        )
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
    assistant = await _resolve_assistant(client, body.agent)
    thread = await client.threads.create(metadata={"surface": "console"})
    run = await client.runs.create(
        thread["thread_id"],
        assistant,
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
    agent = meta.get("assistant_id") or meta.get("graph_id")
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


# ---- self-service: create agents from the console -------------------------------------


@router.get("/api/registry")
async def registry_view() -> dict[str, Any]:
    def _load():
        from agent_factory.registry import load_registry
        from agent_factory.scaffold import list_templates

        reg = load_registry()
        return {
            "teams": [t.model_dump() for t in reg.teams.values()],
            "tools": [t.model_dump(exclude={"impl"}) for t in reg.tools.values()],
            "tiers": [m.model_dump() for m in reg.models.values()],
            "templates": list_templates(),
            "surfaces": ["chat", "sdk", "slack", "mcp", "webhook", "cron"],
        }

    return await asyncio.to_thread(_load)


class NewAgent(BaseModel):
    name: str
    display_name: str
    team: str
    owner: str
    purpose: str
    template: str | None = None
    model_tier: str | None = None
    tools: list[str] | None = None
    approve: list[str] | None = None
    surfaces: list[dict[str, Any]] | None = None
    instructions: str | None = None
    first_example: dict[str, Any] | None = None
    run_gate: bool = False


def _assemble(body: NewAgent):
    from agent_factory.scaffold import build_spec_dict, starter_examples, template_instructions

    overrides: dict[str, Any] = {}
    if body.model_tier:
        overrides["model_tier"] = body.model_tier
    if body.tools is not None:
        overrides["tools"] = body.tools
    if body.approve is not None:
        overrides["oversight"] = {"approve": body.approve}
    if body.surfaces:
        overrides["surfaces"] = body.surfaces
    spec_dict = build_spec_dict(
        name=body.name,
        display_name=body.display_name,
        team=body.team,
        owner=body.owner,
        purpose=body.purpose,
        template=body.template,
        overrides=overrides,
    )
    instructions = body.instructions or template_instructions(body.template, body.display_name)
    examples = starter_examples(body.name, body.template, body.first_example)
    return spec_dict, instructions, examples


def _policy_json(policy) -> dict[str, Any]:
    return {
        "ok": policy.ok,
        "errors": [{"rule": v.rule, "message": v.message} for v in policy.errors],
        "warnings": [{"rule": v.rule, "message": v.message} for v in policy.warnings],
    }


@router.post("/api/agents/validate")
async def validate_new_agent(body: NewAgent) -> dict[str, Any]:
    """Dry run: the same policy the build enforces, before anything is written."""
    from agent_factory.scaffold import validate_only

    def _check():
        spec_dict, _, _ = _assemble(body)
        spec, policy = validate_only(spec_dict)
        if spec is None:
            return {
                "ok": False,
                "errors": [{"rule": "spec.invalid", "message": m} for m in policy],
                "warnings": [],
            }
        out = _policy_json(policy)
        # Policy checks the dataset and instructions on disk; a new agent has neither yet.
        out["errors"] = [
            e for e in out["errors"] if e["rule"] not in ("evals.dataset", "instructions.exists")
        ]
        out["ok"] = not out["errors"]
        return out

    return await asyncio.to_thread(_check)


@router.post("/api/agents")
async def create_new_agent(body: NewAgent, request: Request) -> dict[str, Any]:
    """Write the agent, register an assistant on the factory graph, optionally run the gate."""
    from agent_factory.scaffold import create_agent

    def _create():
        spec_dict, instructions, examples = _assemble(body)
        return create_agent(spec_dict, instructions, examples)

    try:
        spec, policy = await asyncio.to_thread(_create)
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid spec: {e}") from e
    if not policy.ok:
        return {"created": False, "policy": _policy_json(policy)}

    assistant_id = None
    client = _sdk(request)
    try:
        a = await client.assistants.create(
            graph_id="factory",
            config={"configurable": {"agent": spec.name}},
            name=spec.name,
            description=spec.purpose,
            metadata={"team": spec.team, "owner": spec.owner, "created_via": "console"},
            if_exists="do_nothing",
        )
        assistant_id = a.get("assistant_id")
    except Exception as e:  # noqa: BLE001
        policy_note = f"agent written but assistant not registered: {e!r}"[:200]
    else:
        policy_note = None

    report = None
    if body.run_gate:
        from agent_factory.evals import run_gate

        report = (await asyncio.to_thread(run_gate, spec)).to_dict()

    return {
        "created": True,
        "name": spec.name,
        "directory": str(spec.directory),
        "assistant_id": assistant_id,
        "policy": _policy_json(policy),
        "note": policy_note,
        "report": report,
    }
