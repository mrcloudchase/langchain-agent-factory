import pytest
from conftest import person

from factory.agents import store
from factory.lifecycle import promotion
from factory.lifecycle.ledger import ledger


def test_standard_process_needs_a_team_approver_for_production(coder):
    assert promotion.request(coder.name, person("kai")).status == "promoted"
    pending = promotion.request(coder.name, person("kai"))
    assert pending.status == "pending" and pending.to == "production"

    with pytest.raises(promotion.Blocked):
        promotion.decide(pending.request["id"], person("kai"), approve=True)
    done = promotion.decide(pending.request["id"], person("eli"), approve=True)

    assert done.status == "promoted" and promotion.stage(coder.name) == "production"
    assert store().baseline(coder.name)["tool_usage"] == 1.0


def test_regulated_process_needs_two_different_people(support):
    promotion.request(support.name, person("dev"))
    request = promotion.request(support.name, person("dev")).request

    assert promotion.decide(request["id"], person("sam"), approve=True).status == "pending"
    with pytest.raises(promotion.Blocked):
        promotion.decide(request["id"], person("sam"), approve=True)
    assert promotion.decide(request["id"], person("priya"), approve=True).status == "promoted"


def test_only_the_owning_team_promotes(support):
    with pytest.raises(promotion.Blocked):
        promotion.request(support.name, person("kai"))


def test_failed_gate_blocks_and_stage_is_unchanged(support):
    rows = store().dataset(support.name)
    for row in rows:
        row["outputs"]["expected_tools"] = ["escalate_ticket"]
    store().write_dataset(support.name, rows)

    with pytest.raises(promotion.Blocked) as blocked:
        promotion.request(support.name, person("dev"))
    assert blocked.value.report is not None and not blocked.value.report.passed
    assert promotion.stage(support.name) == "dev"


def test_rejection_closes_the_request(radar):
    promotion.request(radar.name, person("noor"))
    request = promotion.request(radar.name, person("noor")).request
    promotion.decide(request["id"], person("rae"), approve=False, comment="needs sources")
    assert ledger().pending(radar.name) == [] and promotion.stage(radar.name) == "staging"
