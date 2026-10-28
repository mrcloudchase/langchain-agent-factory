from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from factory.paths import DATA_DIR


@lru_cache(maxsize=8)
def load_json(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def kb_files() -> list[Path]:
    kb = DATA_DIR / "kb"
    return sorted(kb.glob("*.md")) if kb.exists() else []
