"""Console API with a fake Agent Server client: roles, create, approvals, promotion."""

import pytest
from fastapi.testclient import TestClient

from factory.console.app import app

INTERRUPT = {
    "action_requests": [
        {"name": "issue_refund", "args": {"order_id": "ORD-7781", "amount_usd": 120.0}}
    ],
    "review_configs": [{"action_name": "issue_refund", "allowed_decisions": ["approve", "reject"]}],
}


class FakeSDK:
    def __init__(self):
        self.runs_created = []
        sdk = self

        class Assistants:
            async def search(_s, **kw):
                return [
                    {
                        "assistant_id": "asst-sup",
                        "graph_id": "factory",
                        "name": "support_triage",
                        "config": {"configurable": {"agent": "support_triage"}},
                    }
                ]

            async def create(_s, **kw):
                sdk.assistant_created = kw
                return {"assistant_id": "asst-new", **kw}

        class Threads:
            async def search(_s, **kw):
                if kw.get("status") == "interrupted":
                    return [
                        {
                            "thread_id": "thr-int",
                            "status": "interrupted",
                            "updated_at": "now",
                            "metadata": {
                                "graph_id": "factory",
                                "assistant_id": "asst-sup",
                                "surface": "webhook",
                            },
                        }
                    ]
                return [
                    {
                        "thread_id": "thr-int",
                        "status": "interrupted",
                        "metadata": {"graph_id": "factory", "assistant_id": "asst-sup"},
                        "values": {
                            "messages": [{"type": "human", "content": "Triage ticket T-1001"}]
                        },
                    }
                ]

            async def get(_s, thread_id):
                return {
                    "thread_id": thread_id,
                    "metadata": {"graph_id": "factory", "assistant_id": "asst-sup"},
                }

            async def get_state(_s, thread_id):
                return {
                    "values": {"messages": [{"type": "human", "content": "Triage ticket T-1001"}]},
                    "tasks": [{"interrupts": [{"value": INTERRUPT}]}],
                }

            async def create(_s, **kw):
                return {"thread_id": "thr-new"}

        class Runs:
            async def create(_s, thread_id, assistant_id, **kw):
                sdk.runs_created.append((thread_id, assistant_id, kw))
                return {"run_id": f"run-{len(sdk.runs_created)}"}

        self.assistants, self.threads, self.runs = Assistants(), Threads(), Runs()


@pytest.fixture
def client():
    app.state.sdk_client = FakeSDK()
    return TestClient(app)


def h(user):
    return {"X-Factory-User": user}


def test_page_and_me(client):
    assert "Agent Factory" in client.get("/console").text
    d = client.get("/console/api/me", headers=h("ops-lead@halcyon.example")).json()
    assert d["user"]["role"] == "approver" and d["mode"]["offline"] is True


def test_registry_and_templates(client):
    d = client.get("/console/api/registry").json()
    assert {t["key"] for t in d["templates"]} >= {"claims_processing", "judge"}
    t = client.get("/console/api/templates/claims_processing").json()
    assert t["archetype"] == "workflow" and len(t["steps_full"]) == 4


def test_create_requires_role_and_team(client, tmp_path):
    body = {
        "name": "claims_intake",
        "template": "claims_processing",
        "purpose": "Claims intake for operations from the console.",
    }
    assert client.post("/console/api/agents", json=body).status_code == 401
    r = client.post(
        "/console/api/agents/validate", json=body, headers=h("research-lead@halcyon.example")
    ).json()
    assert not r["ok"]
    r = client.post(
        "/console/api/agents", json=body, headers=h("ops-analyst@halcyon.example")
    ).json()
    assert r["created"] and r["assistant_id"] == "asst-new"
    assert (
        app.state.sdk_client.assistant_created["config"]["configurable"]["agent"] == "claims_intake"
    )
    assert (
        client.post(
            "/console/api/agents", json=body, headers=h("ops-analyst@halcyon.example")
        ).status_code
        == 409
    )
    d = client.get("/console/api/agents/claims_intake").json()
    assert (
        d["archetype"] == "workflow"
        and d["pipeline"]["current"] == "dev"
        and len(d["dataset"]) == 4
    )


def test_run_and_runtime_approval(client, make):
    make("support_triage", name="support_triage")
    r = client.post(
        "/console/api/agents/support_triage/run",
        json={"question": "Triage ticket T-1001"},
        headers=h("support-agent@halcyon.example"),
    ).json()
    assert r["thread_id"] == "thr-new"
    assert app.state.sdk_client.runs_created[-1][1] == "asst-sup"
    a = client.get("/console/api/approvals", headers=h("support-lead@halcyon.example")).json()
    assert (
        a["actions"][0]["agent"] == "support_triage" and a["actions"][0]["tool"] == "issue_refund"
    )
    r = client.post(
        "/console/api/approvals/thr-int",
        json={"decision": "approve"},
        headers=h("support-lead@halcyon.example"),
    ).json()
    assert r["count"] == 1
    assert app.state.sdk_client.runs_created[-1][2]["command"]["resume"]["decisions"] == [
        {"type": "approve"}
    ]
    assert (
        client.post("/console/api/approvals/thr-int", json={"decision": "approve"}).status_code
        == 401
    )


def test_promotion_flow_through_console(client, make):
    make("claims_processing", name="claims_intake")
    ana, omar, priya = (
        h("ops-analyst@halcyon.example"),
        h("ops-lead@halcyon.example"),
        h("platform-lead@halcyon.example"),
    )
    r = client.post("/console/api/agents/claims_intake/promote", json={}, headers=ana).json()
    assert r["ok"] and r["status"] == "promoted" and r["to"] == "staging"
    r = client.post("/console/api/agents/claims_intake/promote", json={}, headers=ana).json()
    assert r["status"] == "pending"
    rid = r["request"]["id"]
    inbox = client.get("/console/api/approvals", headers=omar).json()
    assert inbox["promotions"][0]["can_approve"] and inbox["promotions"][0]["open_gates"] == [
        "approval",
        "platform_approval",
    ]
    assert client.post(f"/console/api/promotions/{rid}", json={}, headers=ana).status_code == 403
    assert (
        client.post(f"/console/api/promotions/{rid}", json={}, headers=omar).json()["status"]
        == "pending"
    )
    assert (
        client.post(f"/console/api/promotions/{rid}", json={}, headers=priya).json()["status"]
        == "promoted"
    )
    assert client.get("/console/api/agents/claims_intake").json()["stage"] == "production"


def test_gate_endpoint_and_delete_requires_platform(client, make):
    make("judge", name="judge")
    r = client.post("/console/api/agents/judge/gate").json()
    assert r["passed"] and r["examples"] == 3
    assert (
        client.delete(
            "/console/api/agents/judge", headers=h("ops-lead@halcyon.example")
        ).status_code
        == 403
    )
    assert (
        client.delete(
            "/console/api/agents/judge", headers=h("platform-lead@halcyon.example")
        ).json()["removed"]
        == "judge"
    )
