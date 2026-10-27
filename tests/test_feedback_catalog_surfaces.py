"""Feedback loop, catalog, and surfaces."""

import json

import pytest
from fastapi.testclient import TestClient

from agent_factory.catalog import build_catalog, write_catalog
from agent_factory.feedback import SAMPLE_TRACES, accept, harvest, pending_path
from agent_factory.spec import load_spec
from agent_factory.surfaces import describe_surfaces
from agent_factory.surfaces.cron import register_crons
from agent_factory.surfaces.webhook import app, render_input


@pytest.fixture
def isolated_agent(tmp_path, monkeypatch):
    """A copy of support_triage's evals dir so harvest/accept don't touch the repo."""
    spec = load_spec("support_triage")
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "dataset.jsonl").write_text(spec.dataset_path.read_text())
    monkeypatch.setattr(type(spec), "directory", property(lambda self: tmp_path))
    return spec


def test_harvest_creates_pending_cases_and_is_idempotent(isolated_agent):
    added = harvest(isolated_agent, source=SAMPLE_TRACES)
    assert len(added) == 1 and added[0]["metadata"]["split"] == "pending"
    assert harvest(isolated_agent, source=SAMPLE_TRACES) == []
    rows = [json.loads(ln) for ln in pending_path(isolated_agent).read_text().splitlines()]
    assert rows[0]["inputs"]["question"].startswith("Triage ticket T-1001")


def test_accept_requires_curation_then_moves_case(isolated_agent):
    added = harvest(isolated_agent, source=SAMPLE_TRACES)
    cid = added[0]["id"]
    with pytest.raises(ValueError):
        accept(isolated_agent, cid)
    p = pending_path(isolated_agent)
    rows = [json.loads(ln) for ln in p.read_text().splitlines()]
    rows[0]["outputs"]["must_contain"] = ["three"]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    moved = accept(isolated_agent, cid)
    assert moved["metadata"]["split"] == "harvested"
    assert cid in isolated_agent.dataset_path.read_text()
    assert p.read_text() == ""


def test_catalog_lists_every_agent_with_governance_fields(tmp_path):
    cat = build_catalog()
    names = {a["name"] for a in cat["agents"]}
    assert names == {"research_digest", "support_triage", "engineering_assistant"}
    support = next(a for a in cat["agents"] if a["name"] == "support_triage")
    refund = next(t for t in support["tools"] if t["name"] == "issue_refund")
    assert refund["sensitive"] and refund["approval"]
    assert {s["kind"] for s in support["surfaces"]} == {"webhook", "chat"}
    j, h = write_catalog(tmp_path)
    assert j.exists() and "Agent Catalog" in h.read_text()


def test_describe_surfaces_mentions_each_kind():
    text = "\n".join(describe_surfaces(load_spec("research_digest")))
    assert "slack" in text and "cron" in text
    text = "\n".join(describe_surfaces(load_spec("engineering_assistant")))
    assert "/mcp" in text and "claude mcp add" in text


def test_cron_dry_run():
    lines = register_crons(load_spec("research_digest"), dry_run=True)
    assert "0 9 * * 1" in lines[0] and "weekly competitive digest" in lines[0]


class FakeSDK:
    def __init__(self):
        self.created = []

        class Threads:
            async def create(_s, **kw):
                return {"thread_id": "thr-1"}

        class Runs:
            async def create(_s, thread_id, assistant_id, **kw):
                self.created.append((thread_id, assistant_id, kw))
                return {"run_id": "run-1"}

        self.threads, self.runs = Threads(), Runs()


def test_webhook_rejects_bad_secret(monkeypatch):
    monkeypatch.setenv("HELPDESK_WEBHOOK_SECRET", "s3cret")
    app.state.sdk_client = FakeSDK()
    client = TestClient(app)
    r = client.post(
        "/webhooks/helpdesk", json={"ticket_id": "T-1001"}, headers={"X-Factory-Secret": "nope"}
    )
    assert r.status_code == 401
    assert app.state.sdk_client.created == []
    r = client.post("/webhooks/helpdesk", json={"ticket_id": "T-1001"})
    assert r.status_code == 401


def test_webhook_starts_run_with_rendered_input(monkeypatch):
    monkeypatch.setenv("HELPDESK_WEBHOOK_SECRET", "s3cret")
    fake = FakeSDK()
    app.state.sdk_client = fake
    client = TestClient(app)
    r = client.post(
        "/webhooks/helpdesk",
        json={"ticket_id": "T-1001", "id": "evt-9"},
        headers={"X-Factory-Secret": "s3cret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["assistant_id"] == "support_triage" and body["run_id"] == "run-1"
    _, assistant, kw = fake.created[0]
    assert kw["input"]["messages"][0]["content"] == "Triage ticket T-1001"
    assert client.get("/webhooks/health").json()["routes"] == ["/webhooks/helpdesk"]


def test_webhook_unknown_route_is_404(monkeypatch):
    monkeypatch.setenv("HELPDESK_WEBHOOK_SECRET", "s3cret")
    app.state.sdk_client = FakeSDK()
    r = TestClient(app).post("/webhooks/nothing", json={}, headers={"X-Factory-Secret": "s3cret"})
    assert r.status_code == 404


def test_render_input_falls_back_on_missing_keys():
    assert render_input({"question": "Triage {ticket_id}"}, {"x": 1}) == {
        "question": "Triage {ticket_id}"
    }
