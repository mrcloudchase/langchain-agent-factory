"""The generated spec: an instance resolved against its template. Never hand-written.

`materialize` is the only way to get one. It is what the policy engine checks and what the
build layer compiles. It is also written to agents/<name>/spec.generated.yaml for review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from factory.core.instance import Instance, SurfaceDecl, load_instance
from factory.core.template import (
    EvalsBlock,
    Step,
    SubAgentDef,
    Template,
    load_template,
)


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(text: str, ctx: dict[str, Any]) -> str:
    return text.format_map(_Safe(ctx))


class Oversight(BaseModel):
    approve: list[str] = Field(default_factory=list)
    allowed_decisions: list[str] = Field(default_factory=lambda: ["approve", "reject"])


class Limits(BaseModel):
    max_model_calls: int = 12
    max_tool_calls: int = 20
    max_tool_calls_per_tool: int | None = None


class AgentSpec(BaseModel):
    name: str
    display_name: str
    template: str
    archetype: str
    team: str
    owner: str
    purpose: str
    process: str
    model_tier: str
    parameters: dict[str, Any]
    instructions: str
    tools: list[str]
    subagents: list[SubAgentDef]
    steps: list[Step]
    oversight: Oversight
    limits: Limits
    surfaces: list[SurfaceDecl]
    filesystem: str
    evals: EvalsBlock
    tags: list[str]

    @property
    def directory(self) -> Path:
        from factory.paths import agent_dir

        return agent_dir(self.name)

    @property
    def dataset_path(self) -> Path:
        return self.directory / "evals" / "dataset.jsonl"

    @property
    def baseline_path(self) -> Path:
        return self.directory / "evals" / "baseline.json"

    @property
    def is_service_agent(self) -> bool:
        return any(s.kind in ("webhook", "cron") for s in self.surfaces)

    @property
    def sensitive_tools(self) -> list[str]:
        return list(self.oversight.approve)


DEFAULT_SURFACE_TARGETS = {
    "webhook": lambda name: {
        "target": f"/webhooks/{name}",
        "input_template": {"question": "{event}"},
    },
    "cron": lambda name: {
        "schedule": "0 9 * * 1",
        "input_template": {"question": "Run your scheduled task"},
    },
    "slack": lambda name: {"target": f"#{name.replace('_', '-')}"},
    "mcp": lambda name: {"target": name},
}


def materialize(inst: Instance, template: Template | None = None) -> AgentSpec:
    t = template or load_template(inst.template)
    params = {**t.default_parameters(), **inst.parameters}
    tools = list(inst.tools) if inst.tools is not None else list(t.tools.default)
    approve = list(inst.approve) if inst.approve is not None else list(t.oversight.required_approve)
    if inst.surfaces is not None:
        surfaces = list(inst.surfaces)
    else:
        surfaces = []
        for kind in t.surfaces.default:
            extra = DEFAULT_SURFACE_TARGETS.get(kind, lambda n: {})(inst.name)
            surfaces.append(SurfaceDecl(kind=kind, **extra))
    # Steps and instructions keep their placeholders; they are rendered at run time with params.
    return AgentSpec(
        name=inst.name,
        display_name=inst.display_name,
        template=t.key,
        archetype=t.archetype,
        team=inst.team,
        owner=inst.owner,
        purpose=inst.purpose,
        process=t.process,
        model_tier=inst.model_tier or t.model_tier,
        parameters=params,
        instructions=render(t.instructions, params),
        tools=tools,
        subagents=t.subagents,
        steps=t.steps,
        oversight=Oversight(approve=approve, allowed_decisions=t.oversight.allowed_decisions),
        limits=Limits(**t.limits) if t.limits else Limits(),
        surfaces=surfaces,
        filesystem=t.filesystem,
        evals=t.evals,
        tags=t.tags,
    )


def write_generated(spec: AgentSpec) -> Path:
    path = spec.directory / "spec.generated.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = spec.model_dump()
    data["_generated"] = "Written by the factory from instance.yaml and the template. Do not edit."
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return path


def load_spec(name: str) -> AgentSpec:
    return materialize(load_instance(name))
