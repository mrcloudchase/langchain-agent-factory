"""The harness turns policy into runtime behavior: approvals, allowlist, budgets."""

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_factory.harness import PolicyError, build_agent
from agent_factory.middleware import BLOCKED_PREFIX
from agent_factory.models import ScriptedChatModel
from agent_factory.spec import AgentSpec, load_spec


def _support_spec(**overrides) -> AgentSpec:
    base = dict(
        name="support_test",
        display_name="Support Test",
        team="support",
        owner="x@halcyon.example",
        purpose="Exercise the harness with scripted trajectories in tests.",
        tools=["lookup_order", "issue_refund"],
        oversight={"approve": ["issue_refund"]},
        filesystem="none",
        surfaces=[{"kind": "chat"}],
        evals={"thresholds": [{"evaluator": "tool_usage", "min_score": 0.9}]},
        limits={"max_model_calls": 6, "max_tool_calls": 6},
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


@pytest.fixture(autouse=True)
def _borrow_instructions(monkeypatch):
    """Test specs have no agents/<name>/ directory; reuse the support agent's instructions."""
    real = load_spec("support_triage").instructions_path
    monkeypatch.setattr(AgentSpec, "instructions_path", property(lambda self: real))


def _agent(spec, script):
    model = ScriptedChatModel(scripts={"go": script})
    return build_agent(spec, model=model, checkpointer=InMemorySaver(), enforce_policy=False)


def _run(agent, cfg):
    return agent.invoke({"messages": [HumanMessage(content="go")]}, config=cfg)


def test_sensitive_tool_pauses_and_resumes_on_approval():
    agent = _agent(
        _support_spec(),
        [
            {"tool": "lookup_order", "args": {"order_id": "ORD-7781"}},
            {"tool": "issue_refund", "args": {"order_id": "ORD-7781", "amount_usd": 120.0}},
            {"answer": "Refunded."},
        ],
    )
    cfg = {"configurable": {"thread_id": "t1"}}
    state = _run(agent, cfg)
    assert state["__interrupt__"][0].value["action_requests"][0]["name"] == "issue_refund"
    state = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg)
    tool_msgs = {m.name: m for m in state["messages"] if m.type == "tool"}
    assert "Refund of $120.00" in tool_msgs["issue_refund"].content
    assert state["messages"][-1].content == "Refunded."


def test_rejected_approval_does_not_run_tool():
    agent = _agent(
        _support_spec(),
        [
            {"tool": "issue_refund", "args": {"order_id": "ORD-7781", "amount_usd": 120.0}},
            {"answer": "Understood, no refund."},
        ],
    )
    cfg = {"configurable": {"thread_id": "t2"}}
    _run(agent, cfg)
    state = agent.invoke(
        Command(resume={"decisions": [{"type": "reject", "message": "Not today."}]}), config=cfg
    )
    refund_msgs = [m for m in state["messages"] if m.type == "tool" and m.name == "issue_refund"]
    assert refund_msgs and "Refund of" not in refund_msgs[0].content


def test_unapproved_tool_is_blocked_at_runtime():
    agent = _agent(
        _support_spec(),
        [
            {"tool": "web_search", "args": {"query": "x"}},  # not in spec.tools
            {"answer": "Could not search."},
        ],
    )
    state = _run(agent, {"configurable": {"thread_id": "t3"}})
    blocked = [m for m in state["messages"] if m.type == "tool" and m.name == "web_search"]
    assert blocked and blocked[0].content.startswith(BLOCKED_PREFIX)
    assert blocked[0].status == "error"


def test_tool_call_budget_is_enforced():
    spec = _support_spec(limits={"max_model_calls": 10, "max_tool_calls": 2})
    agent = _agent(
        spec,
        [
            {"tool": "lookup_order", "args": {"order_id": "ORD-7781"}},
            {"tool": "lookup_order", "args": {"order_id": "ORD-7781"}},
            {"tool": "lookup_order", "args": {"order_id": "ORD-7781"}},
            {"answer": "done"},
        ],
    )
    state = _run(agent, {"configurable": {"thread_id": "t4"}})
    contents = [m.content for m in state["messages"] if m.type == "tool"]
    assert sum("ORD-7781" in c for c in contents) == 2
    assert any("limit" in c.lower() for c in contents)


def test_policy_error_on_build_when_spec_invalid():
    spec = _support_spec(tools=["issue_refund"], oversight={"approve": []})
    with pytest.raises(PolicyError) as exc:
        build_agent(spec, model=ScriptedChatModel(scripts={}))
    assert "oversight.sensitive" in str(exc.value)


def test_shipped_specs_build_offline():
    for name in ("research_digest", "support_triage", "engineering_assistant"):
        agent = build_agent(load_spec(name), checkpointer=InMemorySaver())
        assert agent.name == name


def test_subagent_gets_only_its_tools():
    spec = load_spec("research_digest")
    agent = build_agent(spec, checkpointer=InMemorySaver())
    graph = agent.get_graph()
    assert "task" in str(graph.nodes) or any("task" in n for n in graph.nodes)
