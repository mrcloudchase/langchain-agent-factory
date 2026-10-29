"""Console API. Disk and model work run in threads so the Agent Server's loop never blocks."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from factory import config
from factory.agents import store
from factory.evals.gate import history, run_gate
from factory.lifecycle import catalog, create, feedback, promotion
from factory.lifecycle.ledger import ledger
from factory.org import User, load_org
from factory.server import runs
from factory.server.deps import optional_user, sdk, user
from factory.spec import load_spec
from factory.surfaces import describe

router = APIRouter(prefix="/console/api")


async def off(fn, *args, **kwargs):
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


def _mode() -> dict[str, Any]:
    tier = next(iter(load_org().tiers.values()))
    return {
        "offline": config.offline(),
        "model": tier.model,
        "langsmith": config.langsmith(),
        "project": config.langsmith_project(),
    }


# Identity and organization -----------------------------------------------------------------


@router.get("/session")
async def session(me: User | None = Depends(optional_user)) -> dict:
    org = await off(load_org)
    return {"user": me, "users": list(org.users.values()), "mode": _mode()}


@router.get("/org")
async def organization() -> dict:
    org = await off(load_org)
    return {
        "teams": list(org.teams.values()),
        "users": list(org.users.values()),
        "tiers": list(org.tiers.values()),
        "tools": list(org.tools.values()),
        "processes": list(org.processes.values()),
        "problems": org.problems(),
        "templates": [
            t.model_dump(exclude={"examples"})
            | {"example_questions": [e["inputs"]["question"] for e in t.examples]}
            for t in org.templates.values()
        ],
    }


# Agents ------------------------------------------------------------------------------------


class Draft(BaseModel):
    name: str
    template: str
    team: str | None = None
    display_name: str | None = None
    purpose: str | None = None
    parameters: dict[str, str] = {}
    tools: list[str] | None = None
    surfaces: list[str] | None = None
    examples: list[dict] = []


def _choices(d: Draft) -> dict[str, Any]:
    return d.model_dump(exclude={"examples"})


@router.get("/agents")
async def list_agents() -> list[dict]:
    return await off(catalog.catalog)


@router.post("/agents/review")
async def review(d: Draft, me: User = Depends(user)) -> dict:
    def _review():
        org = load_org()
        agent = create.draft(org, me, **_choices(d))
        return {"agent": agent, "violations": create.review(org, me, agent)}

    return await off(_review)


@router.post("/agents")
async def create_agent(d: Draft, request: Request, me: User = Depends(user)) -> dict:
    agent = await off(create.create, me, examples=d.examples, **_choices(d))
    await runs.assistant_id(sdk(request), agent.name)
    return await off(catalog.card, agent.name)


class Parameters(BaseModel):
    parameters: dict[str, str]


@router.patch("/agents/{name}/parameters")
async def reconfigure(name: str, body: Parameters, me: User = Depends(user)) -> dict:
    await off(create.reconfigure, me, name, body.parameters)
    return await off(catalog.card, name)


@router.delete("/agents/{name}")
async def remove(name: str, me: User = Depends(user)) -> dict:
    if me.role != "platform":
        raise PermissionError("only the platform team removes agents")
    await off(store().delete, name)
    await off(ledger().forget, name)
    return {"removed": name}


@router.get("/agents/{name}")
async def agent_detail(name: str, request: Request) -> dict:
    def _detail():
        s = store()
        return {
            **catalog.card(name),
            "dataset": s.dataset(name),
            "pending_cases": s.pending(name),
            "gates": history(name)[-8:],
            "surfaces_detail": describe(load_spec(name)),
            "instructions": load_spec(name).instructions,
            "steps_full": [x.model_dump() for x in load_spec(name).steps],
            "parameter_labels": {
                p.key: p.label for p in load_org().template(s.load(name).template).parameters
            },
        }

    detail = await off(_detail)
    threads = await sdk(request).threads.search(metadata={"agent": name}, limit=12)
    detail["activity"] = [runs.summary(t) for t in threads]
    return detail


# Runs, runtime approvals, flags ------------------------------------------------------------


class Question(BaseModel):
    question: str


@router.post("/agents/{name}/runs")
async def start(name: str, body: Question, request: Request, me: User = Depends(user)) -> dict:
    await off(load_spec, name)
    return await runs.start_run(sdk(request), name, body.question, surface="console", user=me.id)


@router.get("/threads/{thread_id}")
async def thread(thread_id: str, request: Request) -> dict:
    client = sdk(request)
    meta, state = await asyncio.gather(
        client.threads.get(thread_id), client.threads.get_state(thread_id)
    )
    return {
        "thread_id": thread_id,
        "status": meta.get("status"),
        "agent": (meta.get("metadata") or {}).get("agent"),
        "messages": runs.messages(state),
        "outputs": (state.get("values") or {}).get("outputs"),
        "pending": runs.interrupts(state),
    }


class Decision(BaseModel):
    approve: bool
    message: str = ""


@router.post("/threads/{thread_id}/decision")
async def decide_action(
    thread_id: str, body: Decision, request: Request, me: User = Depends(user)
) -> dict:
    client = sdk(request)
    meta, state = await asyncio.gather(
        client.threads.get(thread_id), client.threads.get_state(thread_id)
    )
    agent = (meta.get("metadata") or {}).get("agent")
    if not me.can_build_for((await off(load_spec, agent)).team):
        raise PermissionError(f"{me.name} cannot approve actions for this agent")
    pending = runs.interrupts(state)
    if not pending:
        raise HTTPException(409, "nothing is waiting for a decision")
    decision = (
        {"type": "approve"}
        if body.approve
        else {"type": "reject", "message": body.message or f"Rejected by {me.name}."}
    )
    return await runs.resume(client, thread_id, agent, [decision] * len(pending), me.id)


class Flag(BaseModel):
    note: str = ""


@router.post("/threads/{thread_id}/flag")
async def flag(thread_id: str, body: Flag, request: Request, me: User = Depends(user)) -> dict:
    client = sdk(request)
    meta, state = await asyncio.gather(
        client.threads.get(thread_id), client.threads.get_state(thread_id)
    )
    msgs = runs.messages(state)
    question = next(m["content"] for m in msgs if m["type"] == "human").split("\n")[-1]
    answer = next(
        (m["content"] for m in reversed(msgs) if m["type"] == "ai" and m["content"].strip()), ""
    )
    latest = await client.runs.list(thread_id, limit=1)
    return await off(
        feedback.flag,
        meta["metadata"]["agent"],
        me,
        question,
        answer,
        body.note,
        latest[0]["run_id"] if latest else None,
    )


class Accept(BaseModel):
    must_contain: list[str]


@router.post("/agents/{name}/cases/{case_id}/accept")
async def accept_case(name: str, case_id: str, body: Accept, me: User = Depends(user)) -> dict:
    return await off(feedback.accept, name, case_id, body.must_contain, me)


# Gates and promotion -----------------------------------------------------------------------


@router.post("/agents/{name}/gate")
async def gate(name: str) -> dict:
    report = await off(run_gate, await off(load_spec, name))
    return report.to_dict()


@router.post("/agents/{name}/promote")
async def promote(name: str, me: User = Depends(user)) -> dict:
    outcome = await off(promotion.request, name, me)
    return {
        "status": outcome.status,
        "to": outcome.to,
        "request": outcome.request,
        "notes": outcome.notes,
    }


@router.get("/approvals")
async def approvals(request: Request, me: User | None = Depends(optional_user)) -> dict:
    client = sdk(request)
    actions = []
    for t in await client.threads.search(status="interrupted", limit=50):
        state = await client.threads.get_state(t["thread_id"])
        meta = t.get("metadata") or {}
        spec = await off(load_spec, meta.get("agent"))
        actions += [
            {
                "thread_id": t["thread_id"],
                "agent": spec.name,
                "team": spec.team,
                "surface": meta.get("surface"),
                "updated_at": t.get("updated_at"),
                **p,
            }
            for p in runs.interrupts(state)
        ]

    def _requests():
        return [
            r | {"team": load_spec(r["agent"]).team, "can_decide": promotion.can_decide(r, me)}
            for r in ledger().pending()
        ]

    return {"actions": actions, "promotions": await off(_requests)}


class Verdict(BaseModel):
    approve: bool
    comment: str = ""


@router.post("/promotions/{request_id}")
async def decide_promotion(request_id: str, body: Verdict, me: User = Depends(user)) -> dict:
    outcome = await off(promotion.decide, request_id, me, body.approve, body.comment)
    return {"status": outcome.status, "to": outcome.to, "notes": outcome.notes}
