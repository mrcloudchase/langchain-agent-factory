"""Org definitions load, every template passes policy, and the rules refuse correctly."""

import pytest

from factory.core.registry import load_registry
from factory.core.template import list_templates
from factory.lifecycle.create import validate_draft


def test_registry_loads_everything():
    reg = load_registry()
    assert {"standard", "regulated"} <= set(reg.processes)
    assert "record_claim_decision" in reg.tools and reg.tools["record_claim_decision"].sensitive
    assert reg.user("ops-lead@halcyon.example").role == "approver"
    assert reg.policy.ceilings["max_model_calls"] >= 20


@pytest.mark.parametrize("key", [t.key for t in list_templates()])
def test_every_template_creates_and_passes_policy(make, key):
    inst, spec, policy = make(key)
    assert policy.ok, [v.message for v in policy.errors]
    assert spec.archetype in ("agent", "workflow")
    assert (spec.directory / "spec.generated.yaml").exists()
    assert spec.dataset_path.exists()


def test_wrong_team_is_refused_before_anything_is_written(tmp_path):
    inst, spec, result = validate_draft(
        name="claims_for_research",
        template="claims_processing",
        team="research",
        owner="r@x",
        purpose="Research team trying the claims template.",
    )
    rules = {v.rule for v in result.errors}
    assert "template.allowed" in rules and "tool.allowed" in rules
    assert not (tmp_path / "agents" / "claims_for_research").exists()


def test_required_approval_cannot_be_removed(make):
    inst, spec, policy = make("claims_processing", approve=[])
    assert not policy.ok
    assert "oversight.required" in {v.rule for v in policy.errors}
    assert not spec.directory.exists(), "a refused create leaves nothing behind"


def test_template_tool_allowlist_and_ceilings(make):
    _, spec, policy = make("judge", tools=["issue_refund"], approve=["issue_refund"])
    rules = {v.rule for v in policy.errors}
    assert "tool.template" in rules and "tool.allowed" in rules


def test_user_scoped_tool_on_unattended_surface_is_refused(make):
    _, spec, policy = make(
        "engineering_assistant", surfaces=[{"kind": "cron", "schedule": "0 9 * * 1"}]
    )
    assert "surface.identity" in {v.rule for v in policy.errors}


def test_policy_severity_is_configurable():
    reg = load_registry()
    assert reg.policy.severity.get("surface.high_risk") == "warning"
