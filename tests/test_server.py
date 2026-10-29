import itertools

import pytest
from fastapi.testclient import TestClient

from factory.server.app import app

ids = itertools.count(1)


class _Assistants:
    def __init__(self):
        self.items = []

    async def search(self, graph_id, metadata, limit):
        return [a for a in self.items if a["metadata"] == metadata][:limit]

    async def create(self, graph_id, config, metadata, name):
        self.items.append({"assistant_id": f"asst-{name}", "metadata": metadata})
        return self.items[-1]


class _Threads:
    def __init__(self):
        self.items = {}

    async def create(self, metadata):
        thread = {"thread_id": f"thread-{next(ids)}", "metadata": metadata, "status": "idle"}
        self.items[thread["thread_id"]] = thread | {"values": {}, "tasks": []}
        return thread

    async def get(self, thread_id):
        return self.items[thread_id]

    async def get_state(self, thread_id):
        return self.items[thread_id]

    async def search(self, metadata=None, status=None, limit=10):
        found = [
            t
            for t in self.items.values()
            if (status is None or t["status"] == status)
            and all(t["metadata"].get(k) == v for k, v in (metadata or {}).items())
        ]
        return found[:limit]


class _Runs:
    def __init__(self):
        self.created = []

    async def create(self, thread_id, assistant_id, **kwargs):
        self.created.append({"thread_id": thread_id, "assistant_id": assistant_id, **kwargs})
        return {"run_id": f"run-{next(ids)}"}

    async def list(self, thread_id, limit=1):
        return []


class FakeSDK:
    def __init__(self):
        self.assistants, self.threads, self.runs = _Assistants(), _Threads(), _Runs()


@pytest.fixture
def sdk():
    app.state.sdk = FakeSDK()
    yield app.state.sdk
    app.state.sdk = None


@pytest.fixture
def client(sdk):
    return TestClient(app)


def as_user(name: str) -> dict:
    return {"X-Factory-User": f"{name}@halcyon.example"}


def test_webhook_rejects_bad_secret(client, sdk, support):
    reply = client.post(
        "/webhooks/billing_support", json={"question": "hi"}, headers={"X-Factory-Secret": "nope"}
    )
    assert reply.status_code == 401 and sdk.runs.created == []


def test_webhook_starts_a_run_tagged_with_its_surface(client, sdk, support):
    reply = client.post(
        "/webhooks/billing_support",
        json={"question": "Triage ticket T-1001"},
        headers={"X-Factory-Secret": "test-secret"},
    )
    assert reply.status_code == 200
    assert sdk.runs.created[0]["metadata"]["surface"] == "webhook"


def test_webhook_only_for_agents_with_that_surface(client, coder):
    reply = client.post(
        "/webhooks/ci_explainer",
        json={"question": "hi"},
        headers={"X-Factory-Secret": "test-secret"},
    )
    assert reply.status_code == 404


def test_console_create_registers_an_assistant(client, sdk):
    body = {"name": "billing_support", "template": "support_agent"}
    assert client.post("/console/api/agents", json=body).status_code == 401

    refused = client.post("/console/api/agents", json=body, headers=as_user("rae"))
    assert refused.status_code == 422 and refused.json()["violations"]

    created = client.post("/console/api/agents", json=body, headers=as_user("dev"))
    assert created.status_code == 200 and created.json()["pipeline"]["current"] == "dev"
    assert sdk.assistants.items[0]["metadata"] == {"agent": "billing_support"}


def test_console_run_and_activity(client, sdk, coder):
    run = client.post(
        "/console/api/agents/ci_explainer/runs",
        json={"question": "Why is CI failing on PR 42?"},
        headers=as_user("kai"),
    )
    assert run.status_code == 200
    detail = client.get("/console/api/agents/ci_explainer").json()
    assert detail["activity"][0]["surface"] == "console" and detail["dataset"]


def test_console_promotion_respects_roles(client, coder):
    blocked = client.post("/console/api/agents/ci_explainer/promote", headers=as_user("chris"))
    assert blocked.status_code == 409
    promoted = client.post("/console/api/agents/ci_explainer/promote", headers=as_user("kai"))
    assert promoted.json() == {
        "status": "promoted",
        "to": "staging",
        "request": None,
        "notes": ["LangSmith not configured; not pushed to Context Hub"],
    }


def test_paused_actions_are_listed_with_the_owning_team(client, sdk, support):
    thread = client.post(
        "/console/api/agents/billing_support/runs",
        json={"question": "Triage ticket T-1001"},
        headers=as_user("dev"),
    ).json()
    sdk.threads.items[thread["thread_id"]] |= {
        "status": "interrupted",
        "tasks": [
            {
                "interrupts": [
                    {
                        "value": {
                            "action_requests": [
                                {"name": "issue_refund", "args": {"order_id": "ORD-7781"}}
                            ]
                        }
                    }
                ]
            }
        ],
    }
    actions = client.get("/console/api/approvals").json()["actions"]
    assert actions[0]["name"] == "issue_refund" and actions[0]["team"] == "support"

    denied = client.post(
        f"/console/api/threads/{thread['thread_id']}/decision",
        json={"approve": True},
        headers=as_user("kai"),
    )
    assert denied.status_code == 403
    approved = client.post(
        f"/console/api/threads/{thread['thread_id']}/decision",
        json={"approve": True},
        headers=as_user("sam"),
    )
    assert approved.status_code == 200
    assert sdk.runs.created[-1]["command"] == {"resume": {"decisions": [{"type": "approve"}]}}
