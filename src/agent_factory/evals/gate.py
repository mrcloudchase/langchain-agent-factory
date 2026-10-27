"""The promotion gate: run evals, compare to thresholds and baseline, emit a report."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langsmith import Client, evaluate
from langsmith.run_helpers import tracing_context
from langsmith.schemas import Example

from agent_factory.evals.evaluators import CODE_EVALUATORS, make_llm_judge
from agent_factory.evals.runner import make_target
from agent_factory.models import is_offline
from agent_factory.paths import STATE_DIR
from agent_factory.registry import load_registry
from agent_factory.spec import AgentSpec

NAMESPACE = uuid.UUID("5d7d1a2e-5a1c-4f9b-9e0a-0000a9e47fac")


@dataclass
class EvaluatorScore:
    key: str
    mean: float
    n: int
    threshold: float | None
    baseline: float | None
    passed: bool
    reason: str = ""


@dataclass
class GateReport:
    agent: str
    mode: str  # "offline" | "langsmith"
    passed: bool
    scores: list[EvaluatorScore]
    failures: list[str]
    examples: int
    experiment_name: str | None = None
    experiment_url: str | None = None
    timestamp: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())
    git_sha: str | None = None
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self) -> Path:
        reports = STATE_DIR / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        path = reports / f"{self.agent}-{self.timestamp.replace(':', '')}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        (reports / f"{self.agent}-latest.json").write_text(json.dumps(self.to_dict(), indent=2))
        return path


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def load_rows(spec: AgentSpec) -> list[dict]:
    rows = []
    for line in spec.dataset_path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def rows_to_examples(rows: list[dict], dataset_id: uuid.UUID) -> list[Example]:
    now = dt.datetime.now(dt.UTC)
    return [
        Example(
            id=uuid.uuid5(NAMESPACE, f"{dataset_id}:{r['id']}"),
            dataset_id=dataset_id,
            inputs=r["inputs"],
            outputs=r.get("outputs", {}),
            metadata={**r.get("metadata", {}), "id": r["id"]},
            created_at=now,
            modified_at=now,
        )
        for r in rows
    ]


def dataset_name_for(spec: AgentSpec) -> str:
    return f"{spec.name}-evals"


def sync_dataset(spec: AgentSpec, client: Client) -> str:
    """Upsert the local JSONL into a LangSmith dataset so the UI shows the same cases."""
    name = dataset_name_for(spec)
    if client.has_dataset(dataset_name=name):
        ds = client.read_dataset(dataset_name=name)
    else:
        ds = client.create_dataset(
            dataset_name=name, description=f"Factory eval set for {spec.display_name}"
        )
    existing = {str(e.id) for e in client.list_examples(dataset_id=ds.id)}
    rows = load_rows(spec)
    new = [
        {
            "id": str(uuid.uuid5(NAMESPACE, f"{ds.id}:{r['id']}")),
            "inputs": r["inputs"],
            "outputs": r.get("outputs", {}),
            "metadata": {**r.get("metadata", {}), "id": r["id"]},
        }
        for r in rows
    ]
    to_create = [e for e in new if e["id"] not in existing]
    to_update = [e for e in new if e["id"] in existing]
    if to_create:
        client.create_examples(dataset_id=ds.id, examples=to_create)
    if to_update:
        client.update_examples(dataset_id=ds.id, updates=to_update)
    return name


def load_baseline(spec: AgentSpec) -> dict[str, float]:
    if spec.baseline_path.exists():
        return json.loads(spec.baseline_path.read_text()).get("scores", {})
    return {}


def save_baseline(spec: AgentSpec, report: GateReport) -> Path:
    spec.baseline_path.parent.mkdir(parents=True, exist_ok=True)
    spec.baseline_path.write_text(
        json.dumps(
            {
                "scores": {s.key: s.mean for s in report.scores},
                "experiment": report.experiment_name,
                "mode": report.mode,
                "timestamp": report.timestamp,
                "git_sha": report.git_sha,
            },
            indent=2,
        )
    )
    return spec.baseline_path


def _aggregate(results) -> tuple[dict[str, list[float]], int, list[dict[str, Any]]]:
    per_key: dict[str, list[float]] = {}
    details: list[dict[str, Any]] = []
    n = 0
    for row in results:
        n += 1
        scores = {}
        for r in row["evaluation_results"]["results"]:
            if r.score is None:
                continue
            per_key.setdefault(r.key, []).append(float(r.score))
            scores[r.key] = float(r.score)
        outputs = row["run"].outputs or {}
        details.append(
            {
                "example": (row["example"].metadata or {}).get("id") or str(row["example"].id)[:8],
                "question": (row["example"].inputs or {}).get("question", "")[:80],
                "scores": scores,
                "tool_calls": outputs.get("tool_calls", []),
                "interrupts": outputs.get("interrupts", []),
                "blocked": outputs.get("blocked", []),
                "answer": (outputs.get("answer") or "")[:400],
            }
        )
    return per_key, n, details


def run_gate(
    spec: AgentSpec,
    *,
    model=None,
    offline: bool | None = None,
    max_concurrency: int = 4,
    experiment_prefix: str | None = None,
) -> GateReport:
    """Evaluate the agent and decide whether it may be promoted."""
    reg = load_registry()
    tier = reg.model_tier(spec.model_tier)
    off_model = is_offline(tier.model if tier else None) if offline is None else offline
    # LangSmith upload is independent of the model mode: a scripted run still produces a
    # real experiment, and its metadata says "offline" so nobody mistakes it for a live one.
    off_langsmith = not os.environ.get("LANGSMITH_API_KEY")

    evaluators: list = list(CODE_EVALUATORS.values())
    if spec.evals.use_llm_judge and not off_model:
        judge_tier = reg.model_tier(reg.default_model_tier)
        evaluators.append(make_llm_judge(judge_tier.model))

    target = make_target(spec, model=model, offline=off_model)
    metadata = {
        "agent": spec.name,
        "team": spec.team,
        "model_tier": spec.model_tier,
        "mode": "offline" if off_model else "live-model",
        "git_sha": git_sha(),
    }
    prefix = experiment_prefix or f"{spec.name}-gate"

    if off_langsmith:
        rows = load_rows(spec)
        data = rows_to_examples(rows, uuid.uuid5(NAMESPACE, dataset_name_for(spec)))
        # No LangSmith key: run the same evaluators locally and keep tracing off so the
        # SDK does not try to upload runs it cannot authenticate.
        offline_client = Client(
            api_key="lsv2_pt_offline_placeholder_00000000",
            auto_batch_tracing=False,
            tracing_sampling_rate=0.0,
        )
        with tracing_context(enabled=False):
            results = evaluate(
                target,
                data=data,
                evaluators=evaluators,
                experiment_prefix=prefix,
                metadata=metadata,
                max_concurrency=max_concurrency,
                upload_results=False,
                client=offline_client,
            )
            per_key, n, details = _aggregate(results)
        mode = "offline"
        url = None
    else:
        client = Client()
        dataset_name = sync_dataset(spec, client)
        results = evaluate(
            target,
            data=dataset_name,
            evaluators=evaluators,
            experiment_prefix=prefix,
            metadata=metadata,
            max_concurrency=max_concurrency,
            client=client,
        )
        mode = "langsmith"
        try:
            url = results.url
        except Exception:  # noqa: BLE001
            url = None
        per_key, n, details = _aggregate(results)

    baseline = load_baseline(spec)
    thresholds = {t.evaluator: t.min_score for t in spec.evals.thresholds}
    scores: list[EvaluatorScore] = []
    failures: list[str] = []
    for key in sorted(set(per_key) | set(thresholds)):
        vals = per_key.get(key, [])
        mean = sum(vals) / len(vals) if vals else 0.0
        thr = thresholds.get(key)
        base = baseline.get(key)
        passed = True
        reason = ""
        if thr is not None and mean < thr:
            passed = False
            reason = f"{mean:.2f} < threshold {thr:.2f}"
        elif base is not None and mean < base - spec.evals.regression_tolerance:
            passed = False
            reason = f"{mean:.2f} regressed from baseline {base:.2f}"
        elif not vals and thr is not None:
            passed = False
            reason = "evaluator produced no scores"
        if not passed:
            failures.append(f"{key}: {reason}")
        scores.append(EvaluatorScore(key, round(mean, 4), len(vals), thr, base, passed, reason))

    report = GateReport(
        agent=spec.name,
        mode=mode,
        passed=not failures,
        scores=scores,
        failures=failures,
        examples=n,
        experiment_name=getattr(results, "experiment_name", None),
        experiment_url=url,
        git_sha=metadata["git_sha"],
        details=details,
    )
    report.save()
    return report
