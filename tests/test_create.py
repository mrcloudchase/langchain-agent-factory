import pytest
from conftest import person

from factory.agents import store
from factory.lifecycle import create
from factory.org import load_org
from factory.policy import check
from factory.spec import load_spec


def rules(refusal: create.Refused) -> set[str]:
    return {v.rule for v in refusal.violations}


def test_create_copies_template_cases_and_adds_live_only_user_cases():
    agent = create.create(
        person("dev"),
        name="billing_support",
        template="support_agent",
        examples=[{"question": "Customer wants a refund on ORD-9", "must_contain": ["ORD-9"]}],
    )
    rows = store().dataset(agent.name)
    assert len(rows) == 5
    assert rows[-1]["metadata"]["split"] == "user" and "offline_trajectory" not in rows[-1]


def test_refused_outside_own_team_and_nothing_is_written():
    with pytest.raises(create.Refused) as refused:
        create.create(person("rae"), name="rae_refunds", template="support_agent")
    assert {"template.team", "tool.team"} <= rules(refused.value)
    with pytest.raises(create.Refused) as refused:
        create.create(person("rae"), name="rae_refunds", template="support_agent", team="support")
    assert rules(refused.value) == {"role.team"}
    assert not store().exists("rae_refunds")


def test_unattended_surface_refuses_tools_that_act_as_a_person():
    with pytest.raises(create.Refused) as refused:
        create.create(
            person("kai"), name="ci_bot", template="coding_agent", surfaces=["mcp", "webhook"]
        )
    assert "surface.template" in rules(refused.value)


def test_name_is_unique(support):
    with pytest.raises(create.Refused) as refused:
        create.create(person("sam"), name=support.name, template="support_agent")
    assert rules(refused.value) == {"name.taken"}


def test_approvals_come_from_the_template_even_with_fewer_tools():
    agent = create.create(
        person("dev"),
        name="lookup_only",
        template="support_agent",
        tools=["lookup_ticket", "knowledge_search", "issue_refund"],
    )
    assert load_spec(agent.name).approvals == ["issue_refund"]


def test_workflow_needs_every_step_tool():
    agent = create.draft(
        load_org(), person("noor"), name="radar", template="ai_research", tools=["paper_search"]
    )
    assert "tool.workflow" in {v.rule for v in check(agent, load_org())}


def test_reconfigure_renders_parameters_into_instructions(support):
    create.reconfigure(person("dev"), support.name, {"refund_policy": "Refunds need a receipt."})
    assert "Refunds need a receipt." in load_spec(support.name).instructions
    with pytest.raises(create.Refused):
        create.reconfigure(person("kai"), support.name, {"refund_policy": "Anything goes."})
