"""Every test runs offline against a fresh agents/ and state directory."""

from __future__ import annotations

import pytest

from factory.lifecycle import create
from factory.org import User, load_org

PROVIDER_KEYS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for key in PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FACTORY_OFFLINE", "1")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("FACTORY_AGENTS", str(tmp_path / "agents"))
    monkeypatch.setenv("FACTORY_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FACTORY_WEBHOOK_SECRET", "test-secret")
    load_org.cache_clear()
    yield
    load_org.cache_clear()


def person(name: str) -> User:
    return load_org().user(f"{name}@halcyon.example")


@pytest.fixture
def support():
    return create.create(person("dev"), name="billing_support", template="support_agent")


@pytest.fixture
def coder():
    return create.create(person("kai"), name="ci_explainer", template="coding_agent")


@pytest.fixture
def radar():
    return create.create(person("noor"), name="research_radar", template="ai_research")
