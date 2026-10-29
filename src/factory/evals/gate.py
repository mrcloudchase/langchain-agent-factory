"""The gate: run an agent's dataset, score it, and compare with thresholds and the baseline.

Offline, cases replay recorded trajectories; cases without one (added by people or harvested
from production) only run live and are counted as skipped. With LangSmith configured, the
dataset is synced and the experiment uploaded so every score links to its traces.
"""

from __future__ import annotations

import contextlib
import io
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langsmith import Client, evaluate
from langsmith.run_helpers import tracing_context

from factory import config
from factory.agents import now, store
from factory.build import build
from factory.evals import runner
from factory.evals.evaluators import EVALUATORS
from factory.spec import Spec

_NAMESPACE = uuid.UUID("5d7d1a2e-5a1c-4f9b-9e0a-0000a9e47fac")


@dataclass
class Score:
    key: str
    mean: float
    threshold: float | None
    baseline: float | None
    passed: bool
    reason: str = ""


@dataclass
class GateReport:
    agent: str
    mode: str
    passed: bool
    scores: list[Score]
    failures: list[str]
    cases: list[dict[str, Any]]
    skipped: int
    experiment_url: str | None = None
    at: str = field(default_factory=now)

    def summary(self) -> dict[str, float]:
        return {s.key: s.mean for s in self.scores}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score(question: str, outputs: dict, reference: dict) -> dict[str, float]:
    return {k: f({"question": question}, outputs, reference) for k, f in EVALUATORS.items()}


def _run_locally(spec: Spec, rows: list[dict]) -> list[dict]:
    graph = build(spec, checkpointer=InMemorySaver())
    with tracing_context(enabled=config.langsmith()):
        results = []
        for row in rows:
            question = row["inputs"]["question"]
            outputs = runner.run(graph, question)
            results.append(
                {
                    "id": row["id"],
                    "question": question,
                    "outputs": outputs,
                    "scores": _score(question, outputs, row["outputs"]),
                }
            )
    return results


def _sync_dataset(client: Client, spec: Spec, rows: list[dict]) -> str:
    name = f"{spec.name}-evals"
    dataset = (
        client.read_dataset(dataset_name=name)
        if client.has_dataset(dataset_name=name)
        else client.create_dataset(name)
    )
    examples = [
        {
            "id": str(uuid.uuid5(_NAMESPACE, f"{name}:{r['id']}")),
            "inputs": r["inputs"],
            "outputs": r["outputs"],
            "metadata": {"case": r["id"]},
        }
        for r in rows
    ]
    existing = {str(e.id) for e in client.list_examples(dataset_id=dataset.id)}
    if fresh := [e for e in examples if e["id"] not in existing]:
        client.create_examples(dataset_id=dataset.id, examples=fresh)
    if known := [e for e in examples if e["id"] in existing]:
        client.update_examples(dataset_id=dataset.id, updates=known)
    return name


def _as_langsmith_evaluator(key: str, fn):
    def evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        return {"key": key, "score": fn(inputs, outputs, reference_outputs)}

    evaluator.__name__ = key
    return evaluator


def _run_in_langsmith(spec: Spec, rows: list[dict]) -> tuple[list[dict], str | None]:
    client = Client()
    graph = build(spec, checkpointer=InMemorySaver())
    evaluators = [_as_langsmith_evaluator(k, f) for k, f in EVALUATORS.items()]
    with contextlib.redirect_stdout(io.StringIO()):
        experiment = evaluate(
            lambda inputs: runner.run(graph, inputs["question"]),
            data=_sync_dataset(client, spec, rows),
            evaluators=evaluators,
            experiment_prefix=f"{spec.name}-gate",
            client=client,
            max_concurrency=4,
            metadata={"agent": spec.name, "team": spec.team, "template": spec.template},
        )
        results = [
            {
                "id": (r["example"].metadata or {}).get("case"),
                "question": r["example"].inputs["question"],
                "outputs": r["run"].outputs or {},
                "scores": {e.key: e.score for e in r["evaluation_results"]["results"]},
            }
            for r in experiment
        ]
    return results, experiment.url


def _judge(spec: Spec, results: list[dict]) -> tuple[list[Score], list[str]]:
    baseline = store().baseline(spec.name)
    scores, failures = [], []
    for key in EVALUATORS:
        values = [r["scores"][key] for r in results if r["scores"].get(key) is not None]
        mean = round(sum(values) / len(values), 4) if values else 0.0
        threshold, base = spec.thresholds.get(key), baseline.get(key)
        reason = ""
        if threshold is not None and mean < threshold:
            reason = f"{mean:.2f} is below the threshold {threshold:.2f}"
        elif base is not None and mean < base - spec.regression_tolerance:
            reason = f"{mean:.2f} regressed from the production baseline {base:.2f}"
        if reason:
            failures.append(f"{key}: {reason}")
        scores.append(Score(key, mean, threshold, base, not reason, reason))
    return scores, failures


def run_gate(spec: Spec) -> GateReport:
    rows = store().dataset(spec.name)
    runnable = [r for r in rows if r.get("offline_trajectory")] if config.offline() else rows
    assert runnable, f"{spec.name} has no cases that can run in this mode"
    if config.langsmith() and not config.offline():
        results, url = _run_in_langsmith(spec, runnable)
    else:
        results, url = _run_locally(spec, runnable), None
    scores, failures = _judge(spec, results)
    report = GateReport(
        agent=spec.name,
        mode="offline" if config.offline() else "live",
        passed=not failures,
        scores=scores,
        failures=failures,
        cases=results,
        skipped=len(rows) - len(runnable),
        experiment_url=url,
    )
    path = config.state_dir() / "reports" / f"{spec.name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(report.to_dict()) + "\n")
    return report


def history(name: str) -> list[dict[str, Any]]:
    path = config.state_dir() / "reports" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
