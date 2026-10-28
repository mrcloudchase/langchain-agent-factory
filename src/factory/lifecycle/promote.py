"""Promotion driven by the process the template names.

`request_promotion` runs the automatic gates for the next transition (policy, evals). If the
transition also needs human approval, the request waits in the ledger until the right people
approve; `approve_promotion` records each approval and finalizes when all are in. Finalizing
sets the stage, saves the baseline on production, and pushes the context bundle to Context Hub.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from factory.core.policy import check_spec
from factory.core.registry import Transition, load_registry
from factory.core.spec import AgentSpec
from factory.evals.gate import GateReport, run_gate, save_baseline
from factory.lifecycle import ledger


class PromotionBlocked(RuntimeError):
    def __init__(self, message: str, report: GateReport | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class PromotionResult:
    agent: str
    to: str
    status: str  # promoted | pending
    request: dict[str, Any] | None = None
    report: GateReport | None = None
    context_hub_url: str | None = None
    notes: list[str] = field(default_factory=list)


def plan(spec: AgentSpec) -> dict[str, Any]:
    """The pipeline for an agent: stages, current stage, and each transition's gates."""
    reg = load_registry()
    proc = reg.process(spec.process)
    stage = ledger.current_stage(spec.name)
    return {
        "process": proc.name,
        "stages": proc.stages,
        "current": stage,
        "next": proc.next_stage(stage),
        "transitions": [t.model_dump(by_alias=True) for t in proc.transitions],
        "pending": ledger.pending_promotions(spec.name),
        "history": ledger.history(spec.name),
    }


def _human_gates(t: Transition) -> list[str]:
    return [g for g in t.gates if g in ("approval", "platform_approval")]


def push_context(spec: AgentSpec, stage: str) -> str | None:
    if not os.environ.get("LANGSMITH_API_KEY"):
        return None
    from langsmith import Client
    from langsmith.schemas import FileEntry

    files = {
        "AGENTS.md": FileEntry(content=spec.instructions or f"# {spec.display_name}\n"),
        "instance.yaml": FileEntry(content=(spec.directory / "instance.yaml").read_text()),
        "spec.generated.yaml": FileEntry(
            content=(spec.directory / "spec.generated.yaml").read_text()
        )
        if (spec.directory / "spec.generated.yaml").exists()
        else FileEntry(content=""),
    }
    if spec.baseline_path.exists():
        files["evals/baseline.json"] = FileEntry(content=spec.baseline_path.read_text())
    return Client().push_agent(
        spec.name,
        files=files,
        description=spec.purpose,
        tags=[spec.team, f"stage:{stage}", *spec.tags],
        is_public=False,
    )


def _finalize(
    spec: AgentSpec, to: str, report: GateReport | None, req: dict[str, Any] | None, by: str | None
) -> PromotionResult:
    res = PromotionResult(agent=spec.name, to=to, status="promoted", request=req, report=report)
    if to == "production":
        if report is not None:
            save_baseline(spec, report)
            res.notes.append("baseline updated from this production run")
        elif req and (req.get("gates") or {}).get("evals"):
            ev = req["gates"]["evals"]
            spec.baseline_path.parent.mkdir(parents=True, exist_ok=True)
            spec.baseline_path.write_text(
                json.dumps(
                    {
                        "scores": ev.get("scores", {}),
                        "mode": ev.get("mode"),
                        "experiment_url": ev.get("experiment_url"),
                        "request_id": req["id"],
                        "timestamp": ledger._now(),
                    },
                    indent=2,
                )
            )
            res.notes.append("baseline saved from the gate run that opened this request")
    url = push_context(spec, to)
    res.context_hub_url = url
    res.notes.append(
        "context pushed to LangSmith Context Hub; move the environment label in the Hub UI"
        if url
        else "LANGSMITH_API_KEY not set: context not pushed to Context Hub"
    )
    ledger.set_stage(
        spec.name,
        to,
        by=by,
        experiment=report.experiment_name if report else None,
        experiment_url=report.experiment_url if report else None,
        scores={s.key: s.mean for s in report.scores} if report else {},
        context_hub_url=url,
        request_id=req["id"] if req else None,
    )
    if req:
        ledger.update_promotion(req["id"], status="promoted")
    return res


def request_promotion(
    spec: AgentSpec,
    to: str | None = None,
    *,
    requested_by: str | None = None,
    offline: bool | None = None,
) -> PromotionResult:
    reg = load_registry()
    proc = reg.process(spec.process)
    if proc is None:
        raise PromotionBlocked(f"unknown process '{spec.process}'")
    current = ledger.current_stage(spec.name)
    to = to or proc.next_stage(current)
    if to is None:
        raise PromotionBlocked(f"{spec.name} is already at the final stage ({current})")
    t = proc.transition(to)
    if t is None or t.from_stage != current:
        raise PromotionBlocked(f"no transition from '{current}' to '{to}' in process '{proc.name}'")
    if ledger.pending_promotions(spec.name):
        raise PromotionBlocked(f"{spec.name} already has a pending promotion request")

    gates: dict[str, Any] = {}
    report = None
    if "policy" in t.gates:
        policy = check_spec(spec)
        gates["policy"] = policy.to_dict()
        if not policy.ok:
            raise PromotionBlocked(
                "policy: " + "; ".join(f"{v.rule}: {v.message}" for v in policy.errors)
            )
    if t.budget:
        over = {k: v for k, v in t.budget.items() if getattr(spec.limits, k, 0) > v}
        gates["budget"] = {"ok": not over, "limit": t.budget, "over": over}
        if over:
            raise PromotionBlocked(f"budget: limits exceed the transition budget {over}")
    if "evals" in t.gates:
        report = run_gate(spec, offline=offline)
        gates["evals"] = {
            "passed": report.passed,
            "failures": report.failures,
            "scores": {s.key: s.mean for s in report.scores},
            "experiment_url": report.experiment_url,
            "mode": report.mode,
        }
        if not report.passed:
            raise PromotionBlocked("evals: " + "; ".join(report.failures), report)

    needs = _human_gates(t)
    if not needs:
        return _finalize(spec, to, report, None, requested_by)
    req = ledger.add_promotion(spec.name, to, requested_by, gates, needs)
    res = PromotionResult(agent=spec.name, to=to, status="pending", request=req, report=report)
    res.notes.append(
        "automatic gates passed; waiting on "
        + ", ".join(
            "a platform approver"
            if n == "platform_approval"
            else f"an approver on team '{spec.team}'"
            for n in needs
        )
    )
    return res


def can_approve(user, spec: AgentSpec, gate: str) -> bool:
    if user is None:
        return False
    if gate == "platform_approval":
        return user.role == "platform"
    return user.role in ("approver", "platform") and (
        user.team == spec.team or user.role == "platform"
    )


def approve_promotion(
    spec: AgentSpec, request_id: str, *, user_id: str, decision: str = "approve", comment: str = ""
) -> PromotionResult:
    reg = load_registry()
    user = reg.user(user_id)
    req = ledger.get_promotion(request_id)
    if req is None or req["agent"] != spec.name or req["status"] != "pending":
        raise PromotionBlocked("no such pending promotion request")
    if decision == "reject":
        ledger.update_promotion(request_id, status="rejected", decided_by=user_id, comment=comment)
        return PromotionResult(
            agent=spec.name,
            to=req["to"],
            status="rejected",
            request=req,
            notes=[f"rejected by {user_id}"],
        )
    satisfied = {a["gate"] for a in req["approvals"]}
    open_gates = [g for g in req["needs"] if g not in satisfied and can_approve(user, spec, g)]
    if not open_gates:
        raise PromotionBlocked(f"{user_id} cannot approve any open gate on this request")
    gate = open_gates[0]
    approvals = [
        *req["approvals"],
        {"gate": gate, "by": user_id, "comment": comment, "at": ledger._now()},
    ]
    req = ledger.update_promotion(request_id, approvals=approvals)
    remaining = [g for g in req["needs"] if g not in {a["gate"] for a in approvals}]
    if remaining:
        return PromotionResult(
            agent=spec.name,
            to=req["to"],
            status="pending",
            request=req,
            notes=[f"{gate} approved by {user_id}; still waiting on {', '.join(remaining)}"],
        )
    report = None
    return _finalize(spec, req["to"], report, req, user_id)
