"""The catalog: every agent with owner, archetype, stage, surfaces, policy, latest gate."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from factory.core.instance import list_instances
from factory.core.policy import check_spec
from factory.core.registry import load_registry
from factory.core.spec import materialize
from factory.core.template import load_template
from factory.lifecycle import ledger
from factory.lifecycle.promote import plan
from factory.paths import CATALOG_DIR, STATE_DIR


def latest_report(name: str) -> dict[str, Any] | None:
    p = STATE_DIR / "reports" / f"{name}-latest.json"
    return json.loads(p.read_text()) if p.exists() else None


def agent_card(inst) -> dict[str, Any]:
    reg = load_registry()
    t = load_template(inst.template)
    spec = materialize(inst, t)
    policy = check_spec(spec, reg, t)
    report = latest_report(spec.name)
    tier = reg.model_tier(spec.model_tier)
    return {
        "name": spec.name,
        "display_name": spec.display_name,
        "template": t.key,
        "archetype": spec.archetype,
        "team": spec.team,
        "owner": spec.owner,
        "purpose": spec.purpose,
        "created_by": inst.created_by,
        "created_at": inst.created_at,
        "process": spec.process,
        "stage": ledger.current_stage(spec.name),
        "model_tier": spec.model_tier,
        "model": tier.model if tier else None,
        "tools": [
            {
                "name": x,
                "sensitive": bool(reg.tool(x) and reg.tool(x).sensitive),
                "approval": x in spec.oversight.approve,
            }
            for x in spec.tools
        ],
        "steps": [{"key": s.key, "title": s.title, "tools": s.tools} for s in spec.steps],
        "subagents": [s.name for s in spec.subagents],
        "surfaces": [s.model_dump(exclude_none=True) for s in spec.surfaces],
        "parameters": spec.parameters,
        "limits": spec.limits.model_dump(),
        "policy": policy.to_dict(),
        "eval": {
            "passed": report["passed"],
            "mode": report["mode"],
            "timestamp": report["timestamp"],
            "scores": {s["key"]: s["mean"] for s in report["scores"]},
            "experiment_url": report.get("experiment_url"),
        }
        if report
        else None,
        "pipeline": plan(spec),
        "tags": spec.tags,
    }


def build_catalog() -> dict[str, Any]:
    reg = load_registry()
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "teams": {k: v.model_dump() for k, v in reg.teams.items()},
        "tools": {k: v.model_dump(exclude={"impl"}) for k, v in reg.tools.items()},
        "processes": {k: v.model_dump(by_alias=True) for k, v in reg.processes.items()},
        "agents": [agent_card(i) for i in list_instances()],
    }


def write_catalog() -> tuple:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    cat = build_catalog()
    j = CATALOG_DIR / "catalog.json"
    j.write_text(json.dumps(cat, indent=2))
    return (j,)
