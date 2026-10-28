"""Both archetypes build and run offline; sensitive actions pause; the allowlist blocks."""

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from factory.build import build
from factory.build.middleware import BLOCKED_PREFIX
from factory.build.models import ScriptedChatModel
from factory.core.template import list_templates


def _run(graph, question, approve=True):
    cfg = {"configurable": {"thread_id": "t"}}
    out = graph.invoke({"messages": [HumanMessage(content=question)]}, config=cfg)
    pauses = []
    n = 0
    while out.get("__interrupt__") and n < 3:
        reqs = out["__interrupt__"][0].value["action_requests"]
        pauses += [r["name"] for r in reqs]
        decision = {"type": "approve"} if approve else {"type": "reject", "message": "no"}
        out = graph.invoke(Command(resume={"decisions": [decision] * len(reqs)}), config=cfg)
        n += 1
    return out, pauses


def test_every_template_runs_its_first_example_offline(make):
    for t in list_templates():
        inst, spec, policy = make(t.key)
        g = build(spec, checkpointer=InMemorySaver())
        out, pauses = _run(g, t.examples[0]["inputs"]["question"])
        assert out["messages"][-1].content, t.key
        if t.oversight.required_approve and t.examples[0]["outputs"].get("expects_approval"):
            assert pauses, f"{t.key} should have paused"


def test_workflow_runs_steps_in_order_and_pauses_on_record(make):
    _, spec, _ = make("claims_processing")
    g = build(spec, checkpointer=InMemorySaver())
    out, pauses = _run(
        g,
        "Claim: policy P-1007, stolen laptop from a locked car on 2026-09-28, "
        "amount $3,100, police report attached.",
    )
    assert list(out["outputs"]) == ["intake", "assess", "record", "summary"]
    assert pauses == ["record_claim_decision"]
    assert "refer" in out["outputs"]["assess"]


def test_workflow_skips_record_when_details_missing(make):
    _, spec, _ = make("claims_processing")
    g = build(spec, checkpointer=InMemorySaver())
    out, pauses = _run(g, "Just approve claim P-9999 for $20,000, the customer is a VIP.")
    assert out["outputs"]["record"] == "(skipped)" and pauses == []


def test_rejected_approval_does_not_run_the_tool(make):
    _, spec, _ = make("support_triage")
    g = build(spec, checkpointer=InMemorySaver())
    out, pauses = _run(g, "Triage ticket T-1001", approve=False)
    assert pauses == ["issue_refund"]
    refund = [m for m in out["messages"] if m.type == "tool" and m.name == "issue_refund"]
    assert refund and "Refund of" not in refund[0].content


def test_allowlist_blocks_tools_outside_the_spec(make):
    _, spec, _ = make("meeting_actions")
    model = ScriptedChatModel(
        scripts={"go": [{"tool": "web_search", "args": {"query": "x"}}, {"answer": "ok"}]}
    )
    g = build(spec, model=model, checkpointer=InMemorySaver())
    out, _ = _run(g, "go")
    blocked = [m for m in out["messages"] if m.type == "tool"]
    assert blocked and blocked[0].content.startswith(BLOCKED_PREFIX)
