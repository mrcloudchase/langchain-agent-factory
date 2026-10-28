"""Webhook surface: auth first, route table from instances, run created through the resolver."""

import pytest
from fastapi.testclient import TestClient

from factory.console.app import app
from factory.surfaces.webhook import webhook_routes


class FakeSDK:
    def __init__(self):
        self.created = []
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

        class Threads:
            async def create(_s, **kw):
                return {"thread_id": "thr-1"}

        class Runs:
            async def create(_s, thread_id, assistant_id, **kw):
                sdk.created.append((thread_id, assistant_id, kw))
                return {"run_id": "run-1"}

        self.assistants, self.threads, self.runs = Assistants(), Threads(), Runs()


@pytest.fixture
def client(make, monkeypatch):
    make("support_triage", name="support_triage")
    webhook_routes.cache_clear()
    monkeypatch.setenv("FACTORY_WEBHOOK_SECRET", "s3cret")
    app.state.sdk_client = FakeSDK()
    return TestClient(app)


def test_webhook_rejects_bad_secret_before_doing_anything(client):
    r = client.post(
        "/webhooks/support_triage",
        json={"ticket_id": "T-1001"},
        headers={"X-Factory-Secret": "nope"},
    )
    assert r.status_code == 401 and app.state.sdk_client.created == []


def test_webhook_starts_run_on_the_resolved_assistant(client):
    r = client.post(
        "/webhooks/support_triage",
        json={"ticket_id": "T-1001", "id": "evt-1"},
        headers={"X-Factory-Secret": "s3cret"},
    )
    assert r.status_code == 200 and r.json()["assistant_id"] == "asst-sup"
    _, assistant, kw = app.state.sdk_client.created[0]
    assert assistant == "asst-sup" and "T-1001" in kw["input"]["messages"][0]["content"]
