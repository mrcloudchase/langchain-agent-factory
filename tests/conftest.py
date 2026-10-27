import logging
import os

import pytest

os.environ["FACTORY_OFFLINE"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGSMITH_API_KEY", None)
logging.getLogger("agent_factory.audit").setLevel(logging.ERROR)


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Keep ledger/reports/catalog writes out of the real repo during tests."""
    import agent_factory.catalog as catalog
    import agent_factory.evals.gate as gate
    import agent_factory.paths as paths
    import agent_factory.promote as promote

    state = tmp_path / ".factory"
    cat = tmp_path / "catalog"
    monkeypatch.setattr(paths, "STATE_DIR", state)
    monkeypatch.setattr(paths, "CATALOG_DIR", cat)
    monkeypatch.setattr(gate, "STATE_DIR", state)
    monkeypatch.setattr(promote, "STATE_DIR", state)
    monkeypatch.setattr(promote, "LEDGER", state / "state.json")
    monkeypatch.setattr(catalog, "STATE_DIR", state)
    monkeypatch.setattr(catalog, "CATALOG_DIR", cat)
    yield
