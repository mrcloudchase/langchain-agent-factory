"""Console API. Handlers never block the event loop: disk and model work run in threads."""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from factory.console.auth import can_build_for, current_user, require
from factory.surfaces.resolve import agent_of, list_assistants, resolve_assistant

router = APIRouter(prefix="/console/api", tags=["console"])


def _sdk(request: Request):
    client = getattr(request.app.state, "sdk_client", None)
    if client is not None:
        return client
    from langgraph_sdk import get_client

    return get_client(url=str(request.base_url).rstrip("/"))


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return "" if content is None else str(content)


def _mode() -> dict[str, Any]:
    from factory.build.models import is_offline
    from factory.core.registry import load_registry

    reg = load_registry()
    tier = reg.model_tier(reg.default_model_tier)
    return {
        "offline": is_offline(tier.model if tier else None),
        "model": tier.model if tier else None,
        "langsmith": bool(os.environ.get("LANGSMITH_API_KEY")),
        "project": os.environ.get("LANGSMITH_PROJECT", "agent-factory"),
    }


# ---- identity --------------------------------------------------------------------------


@router.get("/me")
async def me(user=Depends(current_user)) -> dict[str, Any]:
    from factory.core.registry import load_registry

    reg = load_registry()
    return {
        "user": user.model_dump() if user else None,
        "users": [u.model_dump() for u in reg.users.values()],
        "mode": _mode(),
    }


# ---- catalog and registry ----------------------------------------------------------------


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    from factory.lifecycle.catalog import build_catalog

    return await asyncio.to_thread(build_catalog)


@router.get("/registry")
async def registry_view() -> dict[str, Any]:
    def _load():
        from factory.core.registry import load_registry
        from factory.core.template import list_templates

        reg = load_registry()
        return {
            "teams": [t.model_dump() for t in reg.teams.values()],
            "users": [u.model_dump() for u in reg.users.values()],
            "tools": [t.model_dump(exclude={"impl"}) for t in reg.tools.values()],
            "tiers": [m.model_dump() for m in reg.models.values()],
            "processes": {k: v.model_dump(by_alias=True) for k, v in reg.processes.items()},
            "templates": [t.summary_card() for t in list_templates()],
            "policy": reg.policy.model_dump(),
        }

    return await asyncio.to_thread(_load)


@router.get("/templates/{key}")
async def template_detail(key: str) -> dict[str, Any]:
    def _load():
        from factory.core.template import load_template

        t = load_template(key)
        d = t.summary_card()
        d["instructions"] = t.instructions
        d["steps_full"] = [s.model_dump() for s in t.steps]
        d["example_questions"] = [e["inputs"]["question"] for e in t.examples]
        return d

    try:
        return await asyncio.to_thread(_load)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


# ---- create --------------------------------------------------------------------------------


class NewAgent(BaseModel):
    name: str
    display_name: str | None = None
    template: str
    team: str | None = None
    owner: str | None = None
    purpose: str | None = None
    parameters: dict[str, Any] = {}
    tools: list[str] | None = None
    approve: list[str] | None = None
    surfaces: list[dict[str, Any]] | None = None
    model_tier: str | None = None
    examples: list[dict[str, Any]] = []
    run_gate: bool = False


def _fields(body: NewAgent, user) -> dict[str, Any]:
    return {
        "name": body.name,
        "display_name": body.display_name,
        "template": body.template,
        "team": body.team or (user.team if user else None),
        "owner": body.owner or (user.id if user else "unknown"),
        "purpose": body.purpose,
        "parameters": body.parameters,
        "tools": body.tools,
        "approve": body.approve,
        "surfaces": body.surfaces,
        "model_tier": body.model_tier,
        "created_by": user.id if user else None,
    }


@router.post("/agents/validate")
async def validate_new(body: NewAgent, user=Depends(current_user)) -> dict[str, Any]:
    from factory.lifecycle.create import validate_draft

    def _check():
        inst, spec, result = validate_draft(**_fields(body, user))
        if inst is None:
            return {
                "ok": False,
                "errors": [{"rule": "spec.invalid", "message": m} for m in result],
                "warnings": [],
            }
        out = result.to_dict()
        if not can_build_for(user, inst.team):
            out["errors"].append(
                {
                    "rule": "role.team",
                    "message": f"{user.id if user else 'anonymous'} cannot build for team '{inst.team}'",
                }
            )
            out["ok"] = False
        out["spec"] = spec.model_dump()
        return out

    return await asyncio.to_thread(_check)


@router.post("/agents")
async def create_agent_ep(
    body: NewAgent, request: Request, user=Depends(current_user)
) -> dict[str, Any]:
    from factory.lifecycle.create import create_instance

    require(user, "platform", "builder", "approver")
    fields = _fields(body, user)
    if not can_build_for(user, fields["team"]):
        raise HTTPException(403, f"{user.id} cannot build for team '{fields['team']}'")
    try:
        inst, spec, policy = await asyncio.to_thread(
            create_instance, user_examples=body.examples, **fields
        )
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid: {e}") from e
    if not policy.ok:
        return {"created": False, "policy": policy.to_dict()}
    assistant_id, note = None, None
    try:
        assistant_id = await resolve_assistant(_sdk(request), spec.name)
    except Exception as e:  # noqa: BLE001
        note = f"agent written; assistant not registered on the server: {e!r}"[:200]
    report = None
    if body.run_gate:
        from factory.evals import run_gate

        report = (await asyncio.to_thread(run_gate, spec)).to_dict()
    return {
        "created": True,
        "name": spec.name,
        "directory": str(spec.directory),
        "assistant_id": assistant_id,
        "policy": policy.to_dict(),
        "note": note,
        "report": report,
    }


@router.delete("/agents/{name}")
async def delete_agent(name: str, user=Depends(current_user)) -> dict[str, Any]:
    from factory.core.spec import load_spec
    from factory.lifecycle import ledger

    require(user, "platform")
    spec = await asyncio.to_thread(load_spec, name)
    shutil.rmtree(spec.directory, ignore_errors=True)
    ledger.forget(name)
    return {"removed": name}


# ---- agent page ----------------------------------------------------------------------------


@router.get("/agents/{name}")
async def agent_detail(name: str, request: Request) -> dict[str, Any]:
    def _load():
        import json

        from factory.core.instance import load_instance, read_dataset
        from factory.core.spec import materialize
        from factory.lifecycle.catalog import agent_card
        from factory.lifecycle.feedback import pending_path
        from factory.paths import STATE_DIR
        from factory.surfaces import describe_surfaces

        inst = load_instance(name)
        spec = materialize(inst)
        card = agent_card(inst)
        reports = (
            sorted((STATE_DIR / "reports").glob(f"{name}-20*.json"))
            if (STATE_DIR / "reports").exists()
            else []
        )
        hist = [json.loads(p.read_text()) for p in reports[-8:]]
        pend = pending_path(spec)
        pending_cases = (
            [json.loads(ln) for ln in pend.read_text().splitlines() if ln.strip()]
            if pend.exists()
            else []
        )
        card.update(
            {
                "dataset": read_dataset(inst),
                "gate_history": [
                    {
                        "timestamp": r["timestamp"],
                        "passed": r["passed"],
                        "mode": r["mode"],
                        "scores": {s["key"]: s["mean"] for s in r["scores"]},
                        "experiment_url": r.get("experiment_url"),
                    }
                    for r in hist
                ],
                "surfaces_detail": describe_surfaces(spec),
                "pending_cases": pending_cases,
                "instructions": spec.instructions,
                "steps_full": [s.model_dump() for s in spec.steps],
            }
        )
        return card

    try:
        card = await asyncio.to_thread(_load)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    client = _sdk(request)
    try:
        amap = {a["assistant_id"]: agent_of(a) for a in await list_assistants(client)}
        threads = await client.threads.search(limit=50)
        card["activity"] = [
            _thread_row(t, amap)
            for t in threads
            if _thread_agent(t.get("metadata") or {}, amap) == name
        ][:12]
    except Exception:  # noqa: BLE001
        card["activity"] = []
    return card


def _thread_agent(meta: dict[str, Any], amap: dict[str, str]) -> str:
    gid = meta.get("graph_id")
    if gid and gid != "factory":
        return gid
    return amap.get(meta.get("assistant_id", ""), gid or "?")


def _thread_row(th: dict[str, Any], amap: dict[str, str]) -> dict[str, Any]:
    meta = th.get("metadata") or {}
    msgs = (th.get("values") or {}).get("messages") or []
    first = next((m for m in msgs if m.get("type") == "human"), {})
    last = msgs[-1] if msgs else {}
    return {
        "thread_id": th["thread_id"],
        "agent": _thread_agent(meta, amap),
        "status": th.get("status"),
        "surface": meta.get("surface") or "console",
        "question": _text(first.get("content"))[:140],
        "last": _text(last.get("content"))[:280],
        "tools": [m.get("name") for m in msgs if m.get("type") == "tool"],
        "updated_at": th.get("updated_at"),
    }


# ---- runs and runtime approvals -----------------------------------------------------------


class RunRequest(BaseModel):
    question: str


@router.post("/agents/{name}/run")
async def run_agent(
    name: str, body: RunRequest, request: Request, user=Depends(current_user)
) -> dict[str, Any]:
    client = _sdk(request)
    assistant = await resolve_assistant(client, name)
    thread = await client.threads.create(
        metadata={"surface": "console", "user": user.id if user else None}
    )
    run = await client.runs.create(
        thread["thread_id"],
        assistant,
        input={"messages": [{"role": "user", "content": body.question}]},
        metadata={"surface": "console"},
    )
    return {"thread_id": thread["thread_id"], "run_id": run["run_id"]}


def _parse_interrupts(state: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for task in state.get("tasks") or []:
        for intr in task.get("interrupts") or []:
            value = intr.get("value") if isinstance(intr, dict) else None
            if isinstance(value, dict) and value.get("action_requests"):
                found.append(value)
    for intr in (state.get("values") or {}).get("__interrupt__") or []:
        value = intr.get("value") if isinstance(intr, dict) else None
        if isinstance(value, dict) and value.get("action_requests"):
            found.append(value)
    return found


async def _runtime_pending(client) -> list[dict[str, Any]]:
    amap = {a["assistant_id"]: agent_of(a) for a in await list_assistants(client)}
    out = []
    for th in await client.threads.search(status="interrupted", limit=50):
        state = await client.threads.get_state(th["thread_id"])
        meta = th.get("metadata") or {}
        agent = _thread_agent(meta, amap)
        for value in _parse_interrupts(state):
            cfgs = {c["action_name"]: c for c in value.get("review_configs", [])}
            for req in value["action_requests"]:
                out.append(
                    {
                        "kind": "action",
                        "thread_id": th["thread_id"],
                        "agent": agent,
                        "tool": req["name"],
                        "args": req.get("args", {}),
                        "allowed": cfgs.get(req["name"], {}).get(
                            "allowed_decisions", ["approve", "reject"]
                        ),
                        "surface": meta.get("surface"),
                        "updated_at": th.get("updated_at"),
                    }
                )
    return out


@router.get("/approvals")
async def approvals(request: Request, user=Depends(current_user)) -> dict[str, Any]:
    from factory.core.spec import load_spec
    from factory.lifecycle import ledger
    from factory.lifecycle.promote import can_approve

    client = _sdk(request)
    try:
        actions = await _runtime_pending(client)
        server_ok = True
    except Exception:  # noqa: BLE001
        actions, server_ok = [], False

    def _promos():
        out = []
        for p in ledger.pending_promotions():
            try:
                spec = load_spec(p["agent"])
            except FileNotFoundError:
                continue
            done = {a["gate"] for a in p["approvals"]}
            open_gates = [g for g in p["needs"] if g not in done]
            out.append(
                {
                    "kind": "promotion",
                    **p,
                    "team": spec.team,
                    "open_gates": open_gates,
                    "can_approve": any(can_approve(user, spec, g) for g in open_gates),
                }
            )
        return out

    promos = await asyncio.to_thread(_promos)
    return {"server_ok": server_ok, "actions": actions, "promotions": promos}


class Decision(BaseModel):
    decision: str
    message: str | None = None


@router.post("/approvals/{thread_id}")
async def decide_action(
    thread_id: str, body: Decision, request: Request, user=Depends(current_user)
) -> dict[str, Any]:
    require(user, "approver", "platform", "builder")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    client = _sdk(request)
    th = await client.threads.get(thread_id)
    meta = th.get("metadata") or {}
    assistant = meta.get("assistant_id") or meta.get("graph_id")
    state = await client.threads.get_state(thread_id)
    n = sum(len(v["action_requests"]) for v in _parse_interrupts(state)) or 1
    decision = (
        {"type": "approve"}
        if body.decision == "approve"
        else {"type": "reject", "message": body.message or f"Rejected by {user.id}."}
    )
    run = await client.runs.create(
        thread_id,
        assistant,
        command={"resume": {"decisions": [decision] * n}},
        metadata={"surface": "console", "decision": body.decision, "user": user.id},
    )
    return {"thread_id": thread_id, "run_id": run["run_id"], "decision": body.decision, "count": n}


@router.get("/threads/{thread_id}")
async def thread_detail(thread_id: str, request: Request) -> dict[str, Any]:
    client = _sdk(request)
    state = await client.threads.get_state(thread_id)
    try:
        status = (await client.threads.get(thread_id)).get("status")
    except Exception:  # noqa: BLE001
        status = None
    values = state.get("values") or {}
    return {
        "thread_id": thread_id,
        "status": status,
        "messages": [
            {
                "type": m.get("type"),
                "name": m.get("name"),
                "content": _text(m.get("content"))[:1500],
                "tool_calls": [tc.get("name") for tc in (m.get("tool_calls") or [])],
            }
            for m in values.get("messages") or []
        ],
        "outputs": values.get("outputs"),
        "pending": _parse_interrupts(state),
    }


# ---- gate, promotion, feedback --------------------------------------------------------------


@router.post("/agents/{name}/gate")
async def gate(name: str) -> dict[str, Any]:
    from factory.core.spec import load_spec
    from factory.evals import run_gate

    spec = await asyncio.to_thread(load_spec, name)
    return (await asyncio.to_thread(run_gate, spec)).to_dict()


class PromoteRequest(BaseModel):
    to: str | None = None


@router.post("/agents/{name}/promote")
async def promote_ep(name: str, body: PromoteRequest, user=Depends(current_user)) -> dict[str, Any]:
    from factory.core.spec import load_spec
    from factory.lifecycle.promote import PromotionBlocked, request_promotion

    require(user, "platform", "builder", "approver")
    spec = await asyncio.to_thread(load_spec, name)
    try:
        res = await asyncio.to_thread(request_promotion, spec, body.to, requested_by=user.id)
    except PromotionBlocked as e:
        return {"ok": False, "blocked": str(e), "report": e.report.to_dict() if e.report else None}
    return {
        "ok": True,
        "status": res.status,
        "to": res.to,
        "notes": res.notes,
        "request": res.request,
        "report": res.report.to_dict() if res.report else None,
        "context_hub_url": res.context_hub_url,
    }


class PromotionDecision(BaseModel):
    decision: str = "approve"
    comment: str = ""


@router.post("/promotions/{request_id}")
async def decide_promotion(
    request_id: str, body: PromotionDecision, user=Depends(current_user)
) -> dict[str, Any]:
    from factory.core.spec import load_spec
    from factory.lifecycle import ledger
    from factory.lifecycle.promote import PromotionBlocked, approve_promotion

    require(user, "approver", "platform")
    req = ledger.get_promotion(request_id)
    if req is None:
        raise HTTPException(404, "no such promotion request")
    spec = await asyncio.to_thread(load_spec, req["agent"])
    try:
        res = await asyncio.to_thread(
            approve_promotion,
            spec,
            request_id,
            user_id=user.id,
            decision=body.decision,
            comment=body.comment,
        )
    except PromotionBlocked as e:
        raise HTTPException(403, str(e)) from e
    return {
        "status": res.status,
        "to": res.to,
        "notes": res.notes,
        "context_hub_url": res.context_hub_url,
    }


@router.post("/agents/{name}/harvest")
async def harvest_ep(name: str) -> dict[str, Any]:
    from factory.core.spec import load_spec
    from factory.lifecycle.feedback import harvest

    spec = await asyncio.to_thread(load_spec, name)
    added = await asyncio.to_thread(harvest, spec)
    return {"added": added}


class AcceptCase(BaseModel):
    case_id: str
    must_contain: list[str] = []
    reference: str = ""


@router.post("/agents/{name}/cases/accept")
async def accept_case(name: str, body: AcceptCase, user=Depends(current_user)) -> dict[str, Any]:
    import json

    from factory.core.spec import load_spec
    from factory.lifecycle.feedback import accept, pending_path

    require(user, "platform", "builder", "approver")
    spec = await asyncio.to_thread(load_spec, name)

    def _do():
        p = pending_path(spec)
        rows = (
            [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
            if p.exists()
            else []
        )
        for r in rows:
            if r["id"] == body.case_id:
                r["outputs"]["must_contain"] = body.must_contain
                r["outputs"]["reference"] = body.reference
                r.setdefault(
                    "offline_trajectory",
                    [{"answer": body.reference or " ".join(body.must_contain)}],
                )
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return accept(spec, body.case_id)

    moved = await asyncio.to_thread(_do)
    if moved is None:
        raise HTTPException(404, "no such pending case")
    return {"accepted": moved["id"]}


# ---- admin ---------------------------------------------------------------------------------


class PublishTool(BaseModel):
    name: str
    description: str
    impl: str
    risk: str = "low"
    scope: str = "any"
    sensitive: bool = False
    teams: list[str] = []
    owner: str = ""


@router.post("/admin/tools")
async def publish_tool(body: PublishTool, user=Depends(current_user)) -> dict[str, Any]:
    import yaml

    from factory.build.agent_harness import load_tool
    from factory.core.registry import ToolEntry, reset_registry_cache
    from factory.paths import ORG_DIR

    require(user, "platform")
    entry = ToolEntry.model_validate(body.model_dump())
    try:
        await asyncio.to_thread(load_tool, entry)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"impl does not load: {e}") from e

    def _write():
        path = ORG_DIR / "tools" / "catalog.yaml"
        data = yaml.safe_load(path.read_text()) or {"tools": []}
        data["tools"] = [t for t in data["tools"] if t["name"] != entry.name] + [
            entry.model_dump(exclude_defaults=True)
        ]
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        reset_registry_cache()

    await asyncio.to_thread(_write)
    return {"published": entry.model_dump()}
