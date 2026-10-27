"""Promotion: dev -> staging -> production, gated by evals.

Promotion does three things: runs the gate, records the stage in the factory ledger,
and (online) pushes the agent's context bundle to LangSmith Context Hub so the deployed
runtime and the UI see the same versioned instructions.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_factory.evals.gate import GateReport, run_gate, save_baseline
from agent_factory.paths import STATE_DIR
from agent_factory.policy import check_spec
from agent_factory.spec import AgentSpec, Stage

STAGES: list[Stage] = ["dev", "staging", "production"]
LEDGER = STATE_DIR / "state.json"


class PromotionBlocked(RuntimeError):
    def __init__(self, message: str, report: GateReport | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class PromotionResult:
    agent: str
    stage: Stage
    report: GateReport | None
    context_hub_url: str | None = None
    notes: list[str] = field(default_factory=list)


def load_ledger() -> dict[str, Any]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {}


def save_ledger(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=2))


def current_stage(name: str) -> Stage | None:
    entry = load_ledger().get(name, {})
    for stage in reversed(STAGES):
        if stage in entry:
            return stage
    return None


def push_context(spec: AgentSpec, stage: Stage) -> str | None:
    """Push AGENTS.md + spec to Context Hub. Returns the commit URL, or None when offline."""
    if not os.environ.get("LANGSMITH_API_KEY"):
        return None
    from langsmith import Client
    from langsmith.schemas import FileEntry

    client = Client()
    files = {
        "AGENTS.md": FileEntry(content=spec.load_instructions()),
        "agent.yaml": FileEntry(content=(spec.directory / "agent.yaml").read_text()),
    }
    if spec.baseline_path.exists():
        files["evals/baseline.json"] = FileEntry(content=spec.baseline_path.read_text())
    return client.push_agent(
        spec.name,
        files=files,
        description=spec.purpose,
        tags=[spec.team, f"stage:{stage}", *spec.tags],
        is_public=False,
    )


def promote(
    spec: AgentSpec,
    to: Stage,
    *,
    skip_gate: bool = False,
    offline: bool | None = None,
) -> PromotionResult:
    policy = check_spec(spec)
    if not policy.ok:
        raise PromotionBlocked(
            "policy violations: " + "; ".join(f"{v.rule}: {v.message}" for v in policy.errors)
        )
    if skip_gate and to == "production":
        raise PromotionBlocked("the eval gate cannot be skipped for production")

    report = None
    if not skip_gate:
        report = run_gate(spec, offline=offline)
        if not report.passed:
            raise PromotionBlocked(
                f"eval gate failed for {spec.name}: " + "; ".join(report.failures), report
            )

    result = PromotionResult(agent=spec.name, stage=to, report=report)

    if to == "production" and report is not None:
        save_baseline(spec, report)
        result.notes.append("baseline updated from this production run")

    url = push_context(spec, to)
    result.context_hub_url = url
    if url:
        result.notes.append(
            "context pushed to LangSmith Context Hub; move the "
            f"'{to}' environment label to this commit in the Hub UI"
        )
    else:
        result.notes.append("LANGSMITH_API_KEY not set: context not pushed to Context Hub")

    ledger = load_ledger()
    ledger.setdefault(spec.name, {})[to] = {
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "git_sha": report.git_sha if report else None,
        "experiment": report.experiment_name if report else None,
        "experiment_url": report.experiment_url if report else None,
        "scores": {s.key: s.mean for s in report.scores} if report else {},
        "context_hub_url": url,
    }
    save_ledger(ledger)
    return result


def demote(spec: AgentSpec, stage: Stage) -> None:
    ledger = load_ledger()
    ledger.get(spec.name, {}).pop(stage, None)
    save_ledger(ledger)


def ledger_path() -> Path:
    return LEDGER
