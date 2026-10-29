"""Paths and runtime mode, read from the environment in one place."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_KEYS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def root() -> Path:
    return Path(os.environ.get("FACTORY_ROOT", _PACKAGE_ROOT))


def org_dir() -> Path:
    return root() / "org"


def data_dir() -> Path:
    return root() / "data"


def agents_dir() -> Path:
    return Path(os.environ.get("FACTORY_AGENTS", root() / "agents"))


def state_dir() -> Path:
    return Path(os.environ.get("FACTORY_STATE", root() / ".factory"))


def offline() -> bool:
    """Scripted models and recorded HTTP. Forced by FACTORY_OFFLINE, or no model key present."""
    return _flag("FACTORY_OFFLINE") or not any(os.environ.get(k) for k in _PROVIDER_KEYS)


def recording() -> bool:
    """Live HTTP whose responses are saved as fixtures for offline replay."""
    return _flag("FACTORY_RECORD")


def langsmith() -> bool:
    return bool(os.environ.get("LANGSMITH_API_KEY"))


def langsmith_project() -> str:
    return os.environ.get("LANGSMITH_PROJECT", "agent-factory")


def webhook_secret() -> str:
    return os.environ.get("FACTORY_WEBHOOK_SECRET", "")
