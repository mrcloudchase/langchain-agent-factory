"""The console: pending approvals, decisions, and runs through the Agent Server SDK."""

import pytest
from fastapi.testclient import TestClient

from agent_factory.surfaces.webhook import app

INTERRUPT = {
    "action_requests": [
        {"name": "issue_refund", "args": {"order_id": "ORD-7781", "amount_usd": 120.0}}
    ],
    "review_configs": [{"action_name": "issue_refund", "allowed_decisions": ["approve", "reject"]}],
}


class FakeSDK:
    """Minimal async stand-in for langgraph_sdk's client."""

    def __init__(self):
        self.runs_created = []
        sdk = self

        class Threads:
            async def search(_s, **kw):
                if kw.get("status") == "interrupted":
                    return [
                        {
                            "thread_id": "thr-int",
                            "status": "interrupted",
                            "updated_at": "now",
                            "metadata": {"graph_id": "support_triage", "surface": "webhook"},
                        }
                    ]
                return [
                    {
                        "thread_id": "thr-int",
                        "status": "interrupted",
                        "metadata": {"graph_id": "support_triage"},
                        "values": {
                            "messages": [{"type": "human", "content": "Triage ticket T-1001"}]
                        },
                    },
                    {
                        "thread_id": "thr-done",
                        "status": "idle",
                        "metadata": {"graph_id": "research_digest"},
                        "values": {
                            "messages": [
                                {"type": "human", "content": "hi"},
                                {"type": "tool", "name": "web_search", "content": "x"},
                                {"type": "ai", "content": "done"},
                            ]
                        },
                    },
                ]

            async def get(_s, thread_id):
                return {"thread_id": thread_id, "metadata": {"graph_id": "support_triage"}}

            async def get_state(_s, thread_id):
                if thread_id == "thr-int":
                    return {
                        "values": {
                            "messages": [{"type": "human", "content": "Triage ticket T-1001"}]
                        },
                        "tasks": [{"interrupts": [{"value": INTERRUPT}]}],
                    }
                return {"values": {"messages": [{"type": "ai", "content": "done"}]}, "tasks": []}

            async def create(_s, **kw):
                return {"thread_id": "thr-new"}

        class Runs:
            async def create(_s, thread_id, assistant_id, **kw):
                sdk.runs_created.append((thread_id, assistant_id, kw))
                return {"run_id": f"run-{len(sdk.runs_created)}"}

        self.threads, self.runs = Threads(), Runs()


@pytest.fixture
def client():
    app.state.sdk_client = FakeSDK()
    return TestClient(app)


def test_page_serves():
    r = TestClient(app).get("/console")
    assert r.status_code == 200 and "Agent Factory Console" in r.text


def test_state_lists_agents_pending_and_recent(client):
    d = client.get("/console/api/state").json()
    assert d["server_ok"] and d["mode"]["offline"] is True
    assert {a["name"] for a in d["agents"]} == {
        "research_digest",
        "support_triage",
        "engineering_assistant",
    }
    assert len(d["pending"]) == 1
    p = d["pending"][0]
    assert (
        p["agent"] == "support_triage" and p["tool"] == "issue_refund" and p["surface"] == "webhook"
    )
    assert p["allowed"] == ["approve", "reject"]
    assert [t["agent"] for t in d["recent"]] == ["support_triage", "research_digest"]
    assert d["recent"][1]["tools"] == ["web_search"]


def test_run_creates_thread_and_run(client):
    r = client.post(
        "/console/api/run", json={"agent": "support_triage", "question": "Triage ticket T-1001"}
    )
    assert r.status_code == 200 and r.json()["thread_id"] == "thr-new"
    thread_id, agent, kw = app.state.sdk_client.runs_created[-1]
    assert (
        agent == "support_triage"
        and kw["input"]["messages"][0]["content"] == "Triage ticket T-1001"
    )
    assert kw["metadata"]["surface"] == "console"


def test_approve_resumes_with_one_decision_per_action(client):
    r = client.post("/console/api/approvals/thr-int", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["count"] == 1
    _, agent, kw = app.state.sdk_client.runs_created[-1]
    assert agent == "support_triage"
    assert kw["command"]["resume"]["decisions"] == [{"type": "approve"}]


def test_reject_carries_message_and_bad_decision_is_400(client):
    r = client.post("/console/api/approvals/thr-int", json={"decision": "reject", "message": "No."})
    assert r.json()["decision"] == "reject"
    _, _, kw = app.state.sdk_client.runs_created[-1]
    assert kw["command"]["resume"]["decisions"][0] == {"type": "reject", "message": "No."}
    assert (
        client.post("/console/api/approvals/thr-int", json={"decision": "maybe"}).status_code == 400
    )


def test_thread_detail_and_gate(client):
    d = client.get("/console/api/threads/thr-int").json()
    assert d["pending"][0]["action_requests"][0]["name"] == "issue_refund"
    g = client.post("/console/api/gate", json={"agent": "research_digest"}).json()
    assert g["passed"] and g["mode"] == "offline" and g["examples"] == 4
    assert client.post("/console/api/gate", json={"agent": "nope"}).status_code == 404


def test_promote_skip_is_not_offered_and_blocked_reports(client):
    r = client.post("/console/api/promote", json={"agent": "support_triage", "to": "nowhere"})
    assert r.status_code == 400
    r = client.post(
        "/console/api/promote", json={"agent": "engineering_assistant", "to": "staging"}
    ).json()
    assert r["ok"] and r["stage"] == "staging" and r["report"]["passed"]
