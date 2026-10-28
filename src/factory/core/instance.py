"""Instances: what a team creates. A template plus parameters, at agents/<name>/instance.yaml."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from factory import paths
from factory.paths import agent_dir


class SurfaceDecl(BaseModel):
    kind: str
    target: str | None = None
    schedule: str | None = None
    input_template: dict[str, Any] | None = None


class Instance(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    display_name: str
    template: str
    team: str
    owner: str
    purpose: str = Field(min_length=20)
    parameters: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] | None = None
    approve: list[str] | None = None
    surfaces: list[SurfaceDecl] | None = None
    model_tier: str | None = None
    created_by: str | None = None
    created_at: str = Field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())

    @property
    def directory(self) -> Path:
        return agent_dir(self.name)

    @property
    def dataset_path(self) -> Path:
        return self.directory / "evals" / "dataset.jsonl"

    @property
    def baseline_path(self) -> Path:
        return self.directory / "evals" / "baseline.json"

    def save(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "instance.yaml"
        path.write_text(yaml.safe_dump(self.model_dump(exclude_none=True), sort_keys=False))
        return path


def load_instance(name: str) -> Instance:
    path = agent_dir(name) / "instance.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no agent named '{name}' ({path})")
    return Instance.model_validate(yaml.safe_load(path.read_text()) or {})


def list_instances() -> list[Instance]:
    if not paths.AGENTS_DIR.exists():
        return []
    out = []
    for d in sorted(paths.AGENTS_DIR.iterdir()):
        if (d / "instance.yaml").exists():
            out.append(load_instance(d.name))
    return out


def write_dataset(inst: Instance, rows: list[dict[str, Any]]) -> Path:
    inst.dataset_path.parent.mkdir(parents=True, exist_ok=True)
    inst.dataset_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return inst.dataset_path


def read_dataset(inst: Instance) -> list[dict[str, Any]]:
    if not inst.dataset_path.exists():
        return []
    return [json.loads(ln) for ln in inst.dataset_path.read_text().splitlines() if ln.strip()]
