"""Templates: the organization's definition of an agent, one directory per template.

A template is valid on its own or it does not load. Cross-references to the rest of the
organization (catalog, processes, tiers, teams) are checked by `Org.problems`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Archetype = Literal["agent", "workflow"]
SURFACES = ("chat", "sdk", "mcp", "webhook", "cron")
UNATTENDED_SURFACES = frozenset({"webhook", "cron"})


class Parameter(BaseModel):
    key: str
    label: str
    default: str = ""
    required: bool = True


class Step(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    prompt: str
    tools: list[str] = Field(default_factory=list)


class ToolChoice(BaseModel):
    default: list[str]
    optional: list[str] = Field(default_factory=list)

    @property
    def allowed(self) -> list[str]:
        return [*self.default, *self.optional]


class Cron(BaseModel):
    schedule: str
    question: str


class SurfaceChoice(BaseModel):
    default: list[Literal["chat", "sdk", "mcp", "webhook", "cron"]]
    optional: list[Literal["chat", "sdk", "mcp", "webhook", "cron"]] = Field(default_factory=list)
    cron: Cron | None = None

    @property
    def allowed(self) -> list[str]:
        return [*self.default, *self.optional]


class Limits(BaseModel):
    model_calls: int = Field(gt=0)
    tool_calls: int = Field(gt=0)


class Evals(BaseModel):
    thresholds: dict[str, float]
    regression_tolerance: float = Field(default=0.1, ge=0, le=1)


class Template(BaseModel):
    key: str
    title: str
    archetype: Archetype
    summary: str
    teams: list[str]
    process: str
    model_tier: str
    parameters: list[Parameter] = Field(default_factory=list)
    tools: ToolChoice
    approvals: list[str] = Field(default_factory=list)
    surfaces: SurfaceChoice
    limits: Limits
    filesystem: Literal["none", "read_only"] = "none"
    evals: Evals
    instructions: str
    steps: list[Step] = Field(default_factory=list)
    examples: list[dict[str, Any]]

    @model_validator(mode="after")
    def _invariants(self) -> Template:
        assert set(self.approvals) <= set(self.tools.allowed), "approvals must name template tools"
        assert set(self.surfaces.default) <= set(self.surfaces.allowed)
        assert ("cron" in self.surfaces.allowed) == (self.surfaces.cron is not None), (
            "a cron surface needs a schedule, and a schedule needs a cron surface"
        )
        assert self.instructions.strip(), "instructions.md is required"
        assert self.examples, "examples.jsonl needs at least one example"
        ids = [e["id"] for e in self.examples]
        assert len(ids) == len(set(ids)), "example ids must be unique"
        if self.archetype == "workflow":
            assert self.steps, "a workflow needs steps"
            assert not self.tools.optional, "workflow tools are fixed by its steps"
            step_tools = {t for s in self.steps for t in s.tools}
            assert step_tools == set(self.tools.default), "workflow tools must equal its step tools"
        else:
            assert not self.steps, "an agent template has no steps"
        return self

    @property
    def parameter_defaults(self) -> dict[str, str]:
        return {p.key: p.default for p in self.parameters}


def load_template(directory: Path) -> Template:
    raw = yaml.safe_load((directory / "template.yaml").read_text())
    steps_file = directory / "steps.yaml"
    steps = yaml.safe_load(steps_file.read_text())["steps"] if steps_file.exists() else []
    examples = [
        json.loads(line)
        for line in (directory / "examples.jsonl").read_text().splitlines()
        if line.strip()
    ]
    template = Template.model_validate(
        {
            **raw,
            "steps": steps,
            "instructions": (directory / "instructions.md").read_text(),
            "examples": examples,
        }
    )
    assert template.key == directory.name, f"template key '{template.key}' must match its directory"
    return template


def load_templates(directory: Path) -> dict[str, Template]:
    return {
        d.name: load_template(d)
        for d in sorted(directory.iterdir())
        if (d / "template.yaml").exists()
    }
