"""Trace-to-dataset feedback loop (the Iterate stage of the ADLC).

Flagged production traces (negative feedback, errors, failed online evaluators) become
*pending* eval cases. A human adds the expected behavior and accepts them into the live
dataset, after which the gate enforces them on every promotion. Offline, a sample traces
file plays the role of LangSmith.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from factory.core.spec import AgentSpec
from factory.paths import DATA_DIR

SAMPLE_TRACES = DATA_DIR / "sample_traces.jsonl"


def pending_path(spec: AgentSpec) -> Path:
    return spec.directory / "evals" / "pending.jsonl"


def _question_from_inputs(inputs: dict[str, Any]) -> str | None:
    if "question" in inputs:
        return str(inputs["question"])
    msgs = inputs.get("messages") or []
    for m in msgs:
        if isinstance(m, dict):
            role = m.get("type") or m.get("role")
            if role in ("human", "user"):
                c = m.get("content")
                return c if isinstance(c, str) else json.dumps(c)
    return None


def _answer_from_outputs(outputs: dict[str, Any] | None) -> str:
    if not outputs:
        return ""
    if "answer" in outputs:
        return str(outputs["answer"])
    msgs = outputs.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, dict) and (m.get("type") == "ai" or m.get("role") == "assistant"):
            c = m.get("content")
            return c if isinstance(c, str) else json.dumps(c)
    return ""


def to_pending_row(trace: dict[str, Any], spec: AgentSpec) -> dict[str, Any] | None:
    question = _question_from_inputs(trace.get("inputs") or {})
    if not question:
        return None
    rid = str(trace.get("id", ""))[:8] or "unknown"
    return {
        "id": f"trace-{rid}",
        "inputs": {"question": question},
        "outputs": {
            "expected_tools": [],
            "forbidden_tools": [],
            "must_contain": [],
            "expects_approval": False,
            "reference": "",
            "observed_answer": _answer_from_outputs(trace.get("outputs")),
        },
        "metadata": {
            "split": "pending",
            "source_run": str(trace.get("id", "")),
            "reason": trace.get("reason", ""),
            "harvested_at": dt.datetime.now(dt.UTC).isoformat(),
        },
    }


def fetch_flagged_traces(spec: AgentSpec, *, hours: int = 168, limit: int = 25) -> list[dict]:
    """Pull flagged root runs for this agent from LangSmith."""
    from langsmith import Client

    client = Client()
    project = os.environ.get("LANGSMITH_PROJECT", "agent-factory")
    start = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
    flagged: list[dict] = []
    # 1. Errored runs.
    for run in client.list_runs(
        project_name=project,
        is_root=True,
        error=True,
        start_time=start,
        limit=limit,
        filter=f'eq(name, "{spec.name}")',
    ):
        flagged.append(
            {"id": run.id, "inputs": run.inputs, "outputs": run.outputs, "reason": "error"}
        )
    # 2. Runs with low user feedback or failed online evaluators.
    for run in client.list_runs(
        project_name=project,
        is_root=True,
        start_time=start,
        limit=limit,
        filter=f'and(eq(name, "{spec.name}"), lt(feedback_score, 0.5))',
    ):
        flagged.append(
            {"id": run.id, "inputs": run.inputs, "outputs": run.outputs, "reason": "low_feedback"}
        )
    return flagged


def harvest(spec: AgentSpec, *, source: Path | None = None, hours: int = 168) -> list[dict]:
    """Append new pending cases for this agent. Returns the rows added."""
    if source is None and os.environ.get("LANGSMITH_API_KEY"):
        traces = fetch_flagged_traces(spec, hours=hours)
    else:
        src = source or SAMPLE_TRACES
        traces = []
        if src.exists():
            for line in src.read_text().splitlines():
                if line.strip():
                    t = json.loads(line)
                    if t.get("agent") in (None, spec.name):
                        traces.append(t)
    path = pending_path(spec)
    existing: set[str] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                existing.add(json.loads(line)["id"])
    dataset_ids = {
        json.loads(line)["id"]
        for line in spec.dataset_path.read_text().splitlines()
        if line.strip()
    }
    added = []
    with path.open("a") as fh:
        for t in traces:
            row = to_pending_row(t, spec)
            if row and row["id"] not in existing and row["id"] not in dataset_ids:
                fh.write(json.dumps(row) + "\n")
                existing.add(row["id"])
                added.append(row)
    return added


def accept(spec: AgentSpec, case_id: str) -> dict | None:
    """Move a curated pending case into the live dataset. Requires a reference to be filled in."""
    path = pending_path(spec)
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    keep, moved = [], None
    for r in rows:
        if r["id"] == case_id and moved is None:
            if not r["outputs"].get("reference") and not r["outputs"].get("must_contain"):
                raise ValueError(f"{case_id}: fill in outputs.reference or must_contain first")
            r["metadata"]["split"] = "harvested"
            moved = r
        else:
            keep.append(r)
    if moved is None:
        return None
    path.write_text("".join(json.dumps(r) + "\n" for r in keep))
    with spec.dataset_path.open("a") as fh:
        fh.write(json.dumps(moved) + "\n")
    return moved
