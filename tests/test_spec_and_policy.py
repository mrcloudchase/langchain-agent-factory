"""Spec validation and policy rules: the contract between teams and the platform."""

import pytest
from pydantic import ValidationError

from agent_factory.policy import check_spec
from agent_factory.spec import AgentSpec, list_specs, load_spec


def _spec(**overrides) -> AgentSpec:
    base = dict(
        name="finance_bot",
        display_name="Finance Bot",
        team="support",
        owner="x@halcyon.example",
        purpose="Reconcile refunds against orders for the finance team every night.",
        tools=["lookup_order"],
        surfaces=[{"kind": "chat"}],
        evals={"thresholds": [{"evaluator": "tool_usage", "min_score": 0.9}]},
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


def test_all_shipped_specs_pass_policy():
    specs = list_specs()
    assert {s.name for s in specs} == {"research_digest", "support_triage", "engineering_assistant"}
    for spec in specs:
        result = check_spec(spec)
        assert result.ok, [v.message for v in result.errors]


def test_spec_rejects_bad_name_and_short_purpose():
    with pytest.raises(ValidationError):
        _spec(name="Bad Name")
    with pytest.raises(ValidationError):
        _spec(purpose="too short")


def test_unknown_team_tool_and_tier_are_violations():
    spec = _spec(team="marketing", tools=["nonexistent_tool"], model_tier="gold")
    rules = {v.rule for v in check_spec(spec).errors}
    assert {"team.exists", "tool.exists", "model.exists"} <= rules


def test_team_cannot_use_another_teams_tool():
    spec = _spec(team="research", tools=["issue_refund"], oversight={"approve": ["issue_refund"]})
    rules = {v.rule for v in check_spec(spec).errors}
    assert "tool.allowed" in rules


def test_sensitive_tool_requires_approval():
    spec = _spec(tools=["issue_refund"])  # no oversight.approve
    rules = {v.rule for v in check_spec(spec).errors}
    assert "oversight.sensitive" in rules
    ok = _spec(tools=["issue_refund"], oversight={"approve": ["issue_refund"]})
    assert "oversight.sensitive" not in {v.rule for v in check_spec(ok).errors}


def test_user_scoped_tool_cannot_run_from_service_surface():
    spec = _spec(
        team="engineering",
        tools=["post_pr_comment"],
        oversight={"approve": ["post_pr_comment"]},
        surfaces=[{"kind": "cron", "schedule": "0 9 * * 1"}],
    )
    rules = {v.rule for v in check_spec(spec).errors}
    assert "surface.identity" in rules


def test_premium_tier_restricted_by_team():
    spec = _spec(model_tier="premium")  # support team
    assert "model.allowed" in {v.rule for v in check_spec(spec).errors}


def test_missing_evals_is_a_violation():
    spec = _spec(evals={"thresholds": []})
    assert "evals.required" in {v.rule for v in check_spec(spec).errors}


def test_high_risk_on_unattended_surface_is_a_warning_only():
    spec = load_spec("support_triage")
    result = check_spec(spec)
    assert result.ok
    assert "surface.high_risk" in {v.rule for v in result.warnings}
