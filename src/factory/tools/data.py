"""Fixture data for the stand-in integrations (helpdesk, CI) and the knowledge base."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from factory import config


@cache
def load_json(name: str) -> dict:
    return json.loads((config.data_dir() / name).read_text())


def kb_files() -> list[Path]:
    return sorted((config.data_dir() / "kb").glob("*.md"))
