"""Repository paths. Everything the factory reads or writes is relative to REPO_ROOT."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("FACTORY_ROOT", Path(__file__).resolve().parents[2]))
AGENTS_DIR = REPO_ROOT / "agents"
REGISTRY_DIR = REPO_ROOT / "registry"
STATE_DIR = REPO_ROOT / ".factory"
CATALOG_DIR = REPO_ROOT / "catalog"


def agent_dir(name: str) -> Path:
    return AGENTS_DIR / name
