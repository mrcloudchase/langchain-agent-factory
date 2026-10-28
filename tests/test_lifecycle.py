"""Gate, process-driven promotion with approvals, ledger, catalog, feedback."""

import pytest

from factory.evals import run_gate
from factory.lifecycle import ledger
from factory.lifecycle.catalog import build_catalog
from factory.lifecycle.feedback import SAMPLE_TRACES, harvest
from factory.lifecycle.promote import PromotionBlocked, approve_promotion, plan, request_promotion


def test_gate_passes_for_every_template(make):
    from factory.core.template import list_templates

    for t in list_templates():
        _, spec, _ = make(t.key)
        r = run_gate(spec)
        assert r.passed, (t.key, r.failures)
        assert r.mode == "offline"


def test_user_example_on_a_workflow_scores_offline(make):
    _, spec, _ = make(
        "claims_processing",
        user_examples=[
            {"question": "Claim: hail, $2,100, photos.", "must_contain": ["approve", "2,100"]}
        ],
    )
    r = run_gate(spec)
    assert r.passed and r.examples == 5


def test_standard_process_promotes_to_staging_then_waits_for_an_approver(make):
    _, spec, _ = make("support_triage")
    res = request_promotion(spec, requested_by="support-agent@halcyon.example")
    assert res.status == "promoted" and res.to == "staging"
    assert ledger.current_stage(spec.name) == "staging"
    res = request_promotion(spec, requested_by="support-agent@halcyon.example")
    assert res.status == "pending" and res.request["needs"] == ["approval"]
    with pytest.raises(PromotionBlocked):
        approve_promotion(
            spec, res.request["id"], user_id="support-agent@halcyon.example"
        )  # builder
    done = approve_promotion(spec, res.request["id"], user_id="support-lead@halcyon.example")
    assert done.status == "promoted" and ledger.current_stage(spec.name) == "production"
    assert spec.baseline_path.exists()


def test_regulated_process_needs_team_and_platform_approval(make):
    _, spec, _ = make("claims_processing")
    request_promotion(spec)
    res = request_promotion(spec)
    assert res.request["needs"] == ["approval", "platform_approval"]
    first = approve_promotion(spec, res.request["id"], user_id="ops-lead@halcyon.example")
    assert first.status == "pending"
    with pytest.raises(PromotionBlocked):
        approve_promotion(
            spec, res.request["id"], user_id="ops-lead@halcyon.example"
        )  # cannot approve twice
    second = approve_promotion(spec, res.request["id"], user_id="platform-lead@halcyon.example")
    assert second.status == "promoted"
    p = plan(spec)
    assert p["current"] == "production" and [h["stage"] for h in p["history"]] == [
        "staging",
        "production",
    ]


def test_rejection_closes_the_request(make):
    _, spec, _ = make("support_triage")
    request_promotion(spec)
    res = request_promotion(spec)
    out = approve_promotion(
        spec,
        res.request["id"],
        user_id="support-lead@halcyon.example",
        decision="reject",
        comment="not yet",
    )
    assert out.status == "rejected" and ledger.current_stage(spec.name) == "staging"
    assert ledger.pending_promotions(spec.name) == []


def test_no_skipping_stages(make):
    _, spec, _ = make("meeting_actions")
    with pytest.raises(PromotionBlocked):
        request_promotion(spec, "production")


def test_catalog_reflects_stage_and_policy(make):
    make("judge")
    _, spec, _ = make("support_triage")
    request_promotion(spec)
    cat = build_catalog()
    by = {a["name"]: a for a in cat["agents"]}
    assert by["t_support_triage"]["stage"] == "staging" and by["t_judge"]["stage"] == "dev"
    assert (
        by["t_support_triage"]["policy"]["ok"]
        and by["t_support_triage"]["pipeline"]["next"] == "production"
    )


def test_harvest_creates_pending_cases(make):
    _, spec, _ = make("support_triage", name="support_triage")
    added = harvest(spec, source=SAMPLE_TRACES)
    assert len(added) == 1 and added[0]["metadata"]["split"] == "pending"
