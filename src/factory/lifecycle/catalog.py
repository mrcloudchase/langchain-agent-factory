"""The catalog: one card per agent with what leadership and approvers need to see."""

from __future__ import annotations

from typing import Any

from factory.agents import store
from factory.evals.gate import history
from factory.lifecycle.promotion import pipeline
from factory.org import load_org
from factory.policy import check
from factory.spec import load_spec


def card(name: str) -> dict[str, Any]:
    org = load_org()
    agent = store().load(name)
    spec = load_spec(name)
    reports = history(name)
    last = reports[-1] if reports else None
    return {
        **agent.model_dump(),
        "title": org.template(agent.template).title,
        "archetype": spec.archetype,
        "process": spec.process,
        "pipeline": pipeline(name),
        "tools": [
            {"name": t, "sensitive": org.tools[t].sensitive, "approval": t in spec.approvals}
            for t in spec.tools
        ],
        "steps": [{"key": s.key, "title": s.title, "tools": s.tools} for s in spec.steps],
        "violations": [v.__dict__ for v in check(agent, org)],
        "gate": {k: last[k] for k in ("passed", "mode", "at", "experiment_url", "skipped")}
        | {"scores": {s["key"]: s["mean"] for s in last["scores"]}}
        if last
        else None,
    }


def catalog() -> list[dict[str, Any]]:
    return [card(a.name) for a in store().all()]
