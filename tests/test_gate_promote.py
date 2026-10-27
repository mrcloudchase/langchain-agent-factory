"""The eval gate and promotion: no gate, no production."""

import json

import pytest

from agent_factory.evals import run_gate
from agent_factory.evals.evaluators import answer_contains, oversight, policy_compliance, tool_usage
from agent_factory.promote import PromotionBlocked, current_stage, promote
from agent_factory.spec import load_spec


def test_code_evaluators():
    ref = {
        "expected_tools": ["a", "b"],
        "forbidden_tools": ["z"],
        "must_contain": ["Yes"],
        "expects_approval": True,
    }
    out = {"tool_calls": ["a"], "answer": "yes indeed", "interrupts": ["b"], "blocked": []}
    assert tool_usage({}, out, ref) == 0.5
    assert tool_usage({}, {**out, "tool_calls": ["a", "z"]}, ref) == 0.0
    assert answer_contains({}, out, ref) == 1.0
    assert oversight({}, out, ref) == 1.0
    assert oversight({}, {**out, "interrupts": []}, ref) == 0.0
    assert policy_compliance({}, out, ref) == 1.0
    assert policy_compliance({}, {**out, "blocked": ["x"]}, ref) == 0.0


@pytest.mark.parametrize("name", ["research_digest", "support_triage", "engineering_assistant"])
def test_gate_passes_offline_for_shipped_agents(name):
    report = run_gate(load_spec(name))
    assert report.mode == "offline"
    assert report.examples == 4
    assert report.passed, report.failures
    keys = {s.key for s in report.scores}
    assert keys >= {"tool_usage", "oversight", "policy_compliance", "answer_contains"}


def test_gate_fails_when_dataset_expects_different_behavior(tmp_path, monkeypatch):
    spec = load_spec("support_triage")
    # Copy the dataset and flip one expectation: T-1003 must now get a refund (it must not).
    rows = [json.loads(line) for line in spec.dataset_path.read_text().splitlines() if line.strip()]
    for r in rows:
        if r["id"] == "support-002":
            r["outputs"]["expected_tools"].append("issue_refund")
            r["outputs"]["forbidden_tools"] = []
            r["outputs"]["expects_approval"] = True
    ds = tmp_path / "dataset.jsonl"
    ds.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(type(spec), "dataset_path", property(lambda self: ds))
    report = run_gate(spec)
    assert not report.passed
    assert any(f.startswith("oversight") or f.startswith("tool_usage") for f in report.failures)


def test_gate_detects_regression_against_baseline(tmp_path, monkeypatch):
    spec = load_spec("research_digest")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "scores": {
                    "tool_usage": 1.0,
                    "answer_contains": 1.0,
                    "oversight": 1.0,
                    "policy_compliance": 1.0,
                    "llm_judge": 0.95,
                }
            }
        )
    )
    monkeypatch.setattr(type(spec), "baseline_path", property(lambda self: baseline))
    report = run_gate(spec)
    # llm_judge is in the baseline but not run offline: no scores, no failure (not thresholded)
    assert report.passed, report.failures


def test_promote_records_stage_and_blocks_skip_for_production():
    spec = load_spec("engineering_assistant")
    res = promote(spec, "staging")
    assert res.report and res.report.passed
    assert current_stage("engineering_assistant") == "staging"
    assert any("LANGSMITH_API_KEY not set" in n for n in res.notes)
    with pytest.raises(PromotionBlocked):
        promote(spec, "production", skip_gate=True)


def test_promote_blocked_on_policy_violation(monkeypatch):
    spec = load_spec("support_triage")
    monkeypatch.setattr(spec.oversight, "approve", [])
    with pytest.raises(PromotionBlocked) as exc:
        promote(spec, "staging")
    assert "oversight.sensitive" in str(exc.value)
