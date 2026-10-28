"""Templates: the organization's definition of an agent, as files under org/templates/<key>/."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from factory.paths import TEMPLATES_DIR

Archetype = Literal["agent", "workflow"]


class Parameter(BaseModel):
    key: str
    label: str
    type: Literal["text", "number", "choice"] = "text"
    required: bool = False
    default: Any = None
    help: str = ""
    choices: list[str] = Field(default_factory=list)


class ToolsBlock(BaseModel):
    default: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)


class OversightBlock(BaseModel):
    required_approve: list[str] = Field(default_factory=list)
    allowed_decisions: list[str] = Field(default_factory=lambda: ["approve", "reject"])


class SurfacesBlock(BaseModel):
    default: list[str] = Field(default_factory=lambda: ["chat"])
    allowed: list[str] = Field(default_factory=lambda: ["chat"])


class EvalThreshold(BaseModel):
    evaluator: str
    min_score: float


class EvalsBlock(BaseModel):
    thresholds: list[EvalThreshold] = Field(default_factory=list)
    regression_tolerance: float = 0.1
    use_llm_judge: bool = False


class SubAgentDef(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    model_tier: str | None = None


class Step(BaseModel):
    key: str
    title: str
    prompt: str
    tools: list[str] = Field(default_factory=list)
    require_tool: str | None = None
    skip_unless: dict[str, str] | None = None  # {"output": "<step>", "contains": "<text>"}


class Template(BaseModel):
    key: str
    title: str
    archetype: Archetype
    summary: str
    team_default: str
    allowed_teams: list[str] = Field(default_factory=list)
    process: str = "standard"
    model_tier: str = "standard"
    parameters: list[Parameter] = Field(default_factory=list)
    tools: ToolsBlock = Field(default_factory=ToolsBlock)
    subagents: list[SubAgentDef] = Field(default_factory=list)
    oversight: OversightBlock = Field(default_factory=OversightBlock)
    surfaces: SurfacesBlock = Field(default_factory=SurfacesBlock)
    limits: dict[str, int] = Field(default_factory=dict)
    filesystem: Literal["none", "read_only", "scratch"] = "scratch"
    evals: EvalsBlock = Field(default_factory=EvalsBlock)
    tags: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    instructions: str = ""
    examples: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def directory(self) -> Path:
        return TEMPLATES_DIR / self.key

    def allowed_for(self, team: str) -> bool:
        return not self.allowed_teams or team in self.allowed_teams

    def default_parameters(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.parameters if p.default is not None}

    def summary_card(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "archetype": self.archetype,
            "summary": self.summary,
            "team_default": self.team_default,
            "allowed_teams": self.allowed_teams,
            "process": self.process,
            "model_tier": self.model_tier,
            "parameters": [p.model_dump() for p in self.parameters],
            "tools": self.tools.model_dump(),
            "oversight": self.oversight.model_dump(),
            "surfaces": self.surfaces.model_dump(),
            "steps": [{"key": s.key, "title": s.title, "tools": s.tools} for s in self.steps],
            "pauses_for_human": self.oversight.required_approve,
            "examples": len(self.examples),
            "tags": self.tags,
        }


def _load_template(d: Path) -> Template:
    raw = yaml.safe_load((d / "template.yaml").read_text()) or {}
    steps = []
    if (d / "steps.yaml").exists():
        steps = (yaml.safe_load((d / "steps.yaml").read_text()) or {}).get("steps", [])
    instructions = (d / "instructions.md").read_text() if (d / "instructions.md").exists() else ""
    examples = []
    if (d / "examples.jsonl").exists():
        for line in (d / "examples.jsonl").read_text().splitlines():
            if line.strip():
                examples.append(json.loads(line))
    return Template.model_validate(
        {**raw, "steps": steps, "instructions": instructions, "examples": examples}
    )


@lru_cache(maxsize=1)
def _all() -> dict[str, Template]:
    out = {}
    if TEMPLATES_DIR.exists():
        for d in sorted(TEMPLATES_DIR.iterdir()):
            if (d / "template.yaml").exists():
                t = _load_template(d)
                out[t.key] = t
    return out


def list_templates() -> list[Template]:
    return list(_all().values())


def load_template(key: str) -> Template:
    t = _all().get(key)
    if t is None:
        raise KeyError(f"unknown template '{key}'")
    return t


def reset_template_cache() -> None:
    _all.cache_clear()
