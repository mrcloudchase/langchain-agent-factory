import logging
import os

import pytest

os.environ["FACTORY_OFFLINE"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGSMITH_API_KEY", None)
logging.getLogger("factory.audit").setLevel(logging.ERROR)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Every test gets its own agents/, .factory/, and catalog/ so the repo is never touched."""
    import factory.evals.gate as gate
    import factory.lifecycle.catalog as catalog
    import factory.lifecycle.ledger as ledger
    import factory.paths as paths

    agents = tmp_path / "agents"
    state = tmp_path / ".factory"
    agents.mkdir()
    monkeypatch.setattr(paths, "AGENTS_DIR", agents)
    monkeypatch.setattr(paths, "STATE_DIR", state)
    monkeypatch.setattr(paths, "CATALOG_DIR", tmp_path / "catalog")
    monkeypatch.setattr(gate, "STATE_DIR", state)
    monkeypatch.setattr(catalog, "STATE_DIR", state)
    monkeypatch.setattr(catalog, "CATALOG_DIR", tmp_path / "catalog")
    monkeypatch.setattr(ledger, "LEDGER", state / "ledger.json")
    yield


@pytest.fixture
def make():
    """Create an instance from a template with sensible defaults."""
    from factory.lifecycle.create import create_instance

    def _make(template, name=None, **kw):
        kw.setdefault("owner", "x@halcyon.example")
        kw.setdefault("purpose", "A test agent created from a template for the suite.")
        return create_instance(name=name or f"t_{template}", template=template, **kw)

    return _make
