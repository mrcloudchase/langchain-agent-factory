from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("FACTORY_ROOT", Path(__file__).resolve().parents[2]))
ORG_DIR = REPO_ROOT / "org"
TEMPLATES_DIR = ORG_DIR / "templates"
PROCESSES_DIR = ORG_DIR / "processes"
AGENTS_DIR = REPO_ROOT / "agents"
DATA_DIR = REPO_ROOT / "data"
STATE_DIR = REPO_ROOT / ".factory"
CATALOG_DIR = REPO_ROOT / "catalog"


def agent_dir(name: str) -> Path:
    return AGENTS_DIR / name
