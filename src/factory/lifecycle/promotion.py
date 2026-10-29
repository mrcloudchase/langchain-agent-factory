"""Promotion through the process the template names.

Requesting a promotion runs the automatic checks (policy, evals). If the transition also needs
people, the request waits until each required approver has approved. The requester can never
approve their own request, and one person satisfies at most one approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from factory import config
from factory.agents import store
from factory.evals.gate import GateReport, run_gate
from factory.lifecycle.ledger import ledger
from factory.org import ApprovalKind, Process, User, load_org
from factory.policy import check
from factory.spec import Spec, load_spec


class Blocked(RuntimeError):
    def __init__(self, message: str, report: GateReport | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class Outcome:
    agent: str
    to: str
    status: str
    request: dict[str, Any] | None = None
    report: GateReport | None = None
    notes: list[str] = field(default_factory=list)


def _process(spec: Spec) -> Process:
    return load_org().processes[spec.process]


def stage(name: str) -> str:
    return ledger().stage(name, _process(load_spec(name)).stages[0])


def pipeline(name: str) -> dict[str, Any]:
    spec = load_spec(name)
    process = _process(spec)
    current = stage(name)
    return {
        "process": process.name,
        "description": process.description,
        "stages": process.stages,
        "current": current,
        "next": process.next_stage(current),
        "transitions": {k: v.model_dump() for k, v in process.transitions.items()},
        "pending": ledger().pending(name),
        "history": ledger().history(name),
    }


def request(name: str, by: User) -> Outcome:
    spec = load_spec(name)
    if not by.can_build_for(spec.team):
        raise Blocked(f"{by.name} cannot promote agents for team '{spec.team}'")
    if ledger().pending(name):
        raise Blocked(f"{name} already has a promotion waiting for approval")
    target = _process(spec).next_stage(stage(name))
    if target is None:
        raise Blocked(f"{name} is already in its final stage")
    transition = _process(spec).transitions[target]

    evidence: dict[str, Any] = {}
    report = None
    if "policy" in transition.checks:
        if violations := check(store().load(name), load_org()):
            raise Blocked("policy: " + "; ".join(v.message for v in violations))
        evidence["policy"] = "ok"
    if "evals" in transition.checks:
        report = run_gate(spec)
        evidence["evals"] = {
            "passed": report.passed,
            "mode": report.mode,
            "scores": report.summary(),
            "experiment_url": report.experiment_url,
        }
        if not report.passed:
            raise Blocked("evals: " + "; ".join(report.failures), report)

    if not transition.approvals:
        return _promote(spec, target, evidence, None, by)
    pending = ledger().open_request(name, target, by.id, list(transition.approvals), evidence)
    who = " and ".join(
        "a platform approver" if k == "platform" else f"a {spec.team} approver"
        for k in transition.approvals
    )
    return Outcome(name, target, "pending", pending, report, [f"checks passed; waiting on {who}"])


def _open_kind(req: dict[str, Any], by: User, team: str) -> ApprovalKind | None:
    if by.id == req["requested_by"] or by.id in {a["by"] for a in req["approvals"]}:
        return None
    done = {a["kind"] for a in req["approvals"]}
    return next((k for k in req["needs"] if k not in done and by.can_approve(k, team)), None)


def can_decide(req: dict[str, Any], by: User | None) -> bool:
    return by is not None and _open_kind(req, by, load_spec(req["agent"]).team) is not None


def decide(request_id: str, by: User, approve: bool, comment: str = "") -> Outcome:
    req = ledger().request(request_id)
    if req["status"] != "pending":
        raise Blocked(f"request {request_id} is {req['status']}")
    spec = load_spec(req["agent"])
    kind = _open_kind(req, by, spec.team)
    if kind is None:
        raise Blocked(f"{by.name} cannot approve this request")
    if not approve:
        req = ledger().update_request(
            request_id, status="rejected", decided_by=by.id, comment=comment
        )
        return Outcome(spec.name, req["to"], "rejected", req, notes=[f"rejected by {by.name}"])
    approvals = [*req["approvals"], {"kind": kind, "by": by.id, "comment": comment}]
    req = ledger().update_request(request_id, approvals=approvals)
    remaining = [k for k in req["needs"] if k not in {a["kind"] for a in approvals}]
    if remaining:
        return Outcome(
            spec.name,
            req["to"],
            "pending",
            req,
            notes=[f"{kind} approval recorded; waiting on {', '.join(remaining)}"],
        )
    return _promote(spec, req["to"], req["evidence"], req, by)


def _promote(
    spec: Spec, target: str, evidence: dict[str, Any], req: dict[str, Any] | None, by: User
) -> Outcome:
    notes = []
    evals = evidence.get("evals")
    if target == _process(spec).stages[-1] and evals:
        store().write_baseline(
            spec.name,
            evals["scores"],
            {"mode": evals["mode"], "experiment_url": evals["experiment_url"]},
        )
        notes.append("production baseline saved from the gate run")
    hub_url = _push_context(spec, target)
    notes.append(
        "versioned in LangSmith Context Hub"
        if hub_url
        else "LangSmith not configured; not pushed to Context Hub"
    )
    ledger().advance(
        spec.name,
        target,
        by=by.id,
        request=req["id"] if req else None,
        scores=evals["scores"] if evals else {},
        experiment_url=evals["experiment_url"] if evals else None,
        context_hub_url=hub_url,
    )
    if req:
        ledger().update_request(req["id"], status="promoted")
    return Outcome(spec.name, target, "promoted", req, notes=notes)


def _push_context(spec: Spec, target: str) -> str | None:
    if not config.langsmith():
        return None
    from langsmith import Client
    from langsmith.schemas import FileEntry

    agent_file = store().directory(spec.name) / "agent.yaml"
    files = {
        "AGENTS.md": FileEntry(content=spec.instructions),
        "agent.yaml": FileEntry(content=agent_file.read_text()),
    }
    return Client().push_agent(
        spec.name,
        files=files,
        description=spec.purpose,
        tags=[spec.team, spec.template, f"stage:{target}"],
    )
