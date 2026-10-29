from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver

from factory.build import build
from factory.build.middleware import BLOCKED_PREFIX, ToolAllowlist
from factory.evals import runner
from factory.spec import load_spec


def run(name: str, question: str, **kwargs) -> dict:
    return runner.run(build(load_spec(name), checkpointer=InMemorySaver()), question, **kwargs)


def test_support_agent_pauses_before_refunding(support):
    out = run(support.name, "Triage ticket T-1001")
    assert out["approvals"] == ["issue_refund"]
    assert "issue_refund" in out["tool_calls"] and "$120.00" in out["answer"]


def test_support_agent_does_not_refund_ineligible_orders(support):
    out = run(support.name, "Triage ticket T-1003")
    assert "issue_refund" not in out["tool_calls"] and out["approvals"] == []


def test_coding_agent_reads_ci_before_answering(coder):
    out = run(coder.name, "Why is CI failing on PR 42?")
    assert out["tool_calls"][0] == "read_ci_status"
    assert "test_webhook_rejects_bad_secret" in out["answer"]


def test_research_workflow_runs_its_steps_on_recorded_live_data(radar):
    out = run(
        radar.name, "What did LangGraph and Deep Agents ship recently, and does it matter for us?"
    )
    assert "package_releases" in out["tool_calls"]
    assert "pypi.org/project/langgraph" in out["answer"]


def test_allowlist_refuses_tools_outside_the_approved_set():
    allowlist = ToolAllowlist("agent", {"lookup_ticket"})
    request = SimpleNamespace(tool_call={"name": "issue_refund", "id": "call-1", "args": {}})
    reply = allowlist.wrap_tool_call(request, lambda _: "executed")
    assert reply.content.startswith(BLOCKED_PREFIX) and reply.status == "error"
    allowed = SimpleNamespace(tool_call={"name": "lookup_ticket", "id": "call-2", "args": {}})
    assert allowlist.wrap_tool_call(allowed, lambda _: "executed") == "executed"
