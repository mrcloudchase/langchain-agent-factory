"""Agents: what teams create. An agent is a template plus the team's choices, stored on disk.

Layout per agent:  agents/<name>/agent.yaml, evals/dataset.jsonl, evals/pending.jsonl,
evals/baseline.json. The agent file records decisions only; everything else is derived.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from factory import config

NAME_PATTERN = r"^[a-z][a-z0-9_]{2,40}$"


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class Agent(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    display_name: str
    template: str
    team: str
    owner: str
    purpose: str = Field(min_length=10)
    parameters: dict[str, str]
    tools: list[str]
    surfaces: list[str]
    created_by: str
    created_at: str = Field(default_factory=now)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return (
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if path.exists()
        else []
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class AgentStore:
    """File-backed storage for agents. One instance per root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, name: str) -> Path:
        return self.root / name

    def exists(self, name: str) -> bool:
        return (self.directory(name) / "agent.yaml").exists()

    def load(self, name: str) -> Agent:
        path = self.directory(name) / "agent.yaml"
        if not path.exists():
            raise FileNotFoundError(f"no agent named '{name}'")
        return Agent.model_validate(yaml.safe_load(path.read_text()))

    def all(self) -> list[Agent]:
        if not self.root.exists():
            return []
        return [
            self.load(d.name) for d in sorted(self.root.iterdir()) if (d / "agent.yaml").exists()
        ]

    def save(self, agent: Agent) -> None:
        path = self.directory(agent.name) / "agent.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(agent.model_dump(), sort_keys=False, allow_unicode=True))

    def delete(self, name: str) -> None:
        shutil.rmtree(self.directory(name), ignore_errors=True)

    # Evaluation data ---------------------------------------------------------------------

    def dataset(self, name: str) -> list[dict[str, Any]]:
        return _jsonl(self.directory(name) / "evals" / "dataset.jsonl")

    def write_dataset(self, name: str, rows: list[dict[str, Any]]) -> None:
        _write_jsonl(self.directory(name) / "evals" / "dataset.jsonl", rows)

    def pending(self, name: str) -> list[dict[str, Any]]:
        return _jsonl(self.directory(name) / "evals" / "pending.jsonl")

    def write_pending(self, name: str, rows: list[dict[str, Any]]) -> None:
        _write_jsonl(self.directory(name) / "evals" / "pending.jsonl", rows)

    def baseline(self, name: str) -> dict[str, float]:
        path = self.directory(name) / "evals" / "baseline.json"
        return json.loads(path.read_text())["scores"] if path.exists() else {}

    def write_baseline(self, name: str, scores: dict[str, float], source: dict[str, Any]) -> None:
        path = self.directory(name) / "evals" / "baseline.json"
        path.write_text(json.dumps({"scores": scores, "at": now(), **source}, indent=2))


def store() -> AgentStore:
    return AgentStore(config.agents_dir())
