from factory.agents import store
from factory.evals.gate import _judge, run_gate
from factory.spec import load_spec


def test_gate_passes_template_cases(support):
    report = run_gate(load_spec(support.name))
    assert report.passed and report.mode == "offline" and len(report.cases) == 4


def test_gate_fails_below_threshold(support):
    rows = store().dataset(support.name)
    for row in rows:
        row["outputs"]["must_contain"] = ["a phrase no answer contains"]
    store().write_dataset(support.name, rows)
    report = run_gate(load_spec(support.name))
    assert not report.passed
    assert any(f.startswith("answer_contains") for f in report.failures)


def test_cases_without_a_recording_are_skipped_offline(support):
    rows = store().dataset(support.name)
    rows.append({"id": "live-1", "inputs": {"question": "Hi"}, "outputs": {"must_contain": ["hi"]}})
    store().write_dataset(support.name, rows)
    assert run_gate(load_spec(support.name)).skipped == 1


def test_regression_from_production_baseline_fails_even_above_threshold(support):
    spec = load_spec(support.name)
    store().write_baseline(support.name, {"answer_contains": 1.0}, {"mode": "live"})
    results = [{"scores": {"answer_contains": 0.85}}]
    scores, failures = _judge(spec, results)
    score = next(s for s in scores if s.key == "answer_contains")
    assert score.mean >= spec.thresholds["answer_contains"] and not score.passed
    assert "regressed" in score.reason and any(f.startswith("answer_contains") for f in failures)
