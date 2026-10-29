"""The spec: an agent resolved against its template and the organization. Always derived."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from factory.agents import Agent, store
from factory.org import Org, load_org
from factory.templates import UNATTENDED_SURFACES, Cron, Limits, Step


class _KeepMissing(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(text: str, values: dict[str, Any]) -> str:
    """Fill known placeholders and leave the rest (step outputs are filled at run time)."""
    return text.format_map(_KeepMissing(values))


class Spec(BaseModel):
    name: str
    display_name: str
    template: str
    archetype: str
    team: str
    owner: str
    purpose: str
    process: str
    model: str
    model_params: dict[str, Any]
    instructions: str
    steps: list[Step]
    tools: list[str]
    approvals: list[str]
    surfaces: list[str]
    cron: Cron | None
    limits: Limits
    filesystem: str
    thresholds: dict[str, float]
    regression_tolerance: float

    @property
    def unattended(self) -> bool:
        return bool(UNATTENDED_SURFACES & set(self.surfaces))


def materialize(agent: Agent, org: Org) -> Spec:
    t = org.template(agent.template)
    tier = org.tiers[t.model_tier]
    params = {**t.parameter_defaults, **agent.parameters}
    return Spec(
        name=agent.name,
        display_name=agent.display_name,
        template=t.key,
        archetype=t.archetype,
        team=agent.team,
        owner=agent.owner,
        purpose=agent.purpose,
        process=t.process,
        model=tier.model,
        model_params=tier.params,
        instructions=render(t.instructions, params),
        steps=[s.model_copy(update={"prompt": render(s.prompt, params)}) for s in t.steps],
        tools=agent.tools,
        approvals=[x for x in t.approvals if x in agent.tools],
        surfaces=agent.surfaces,
        cron=t.surfaces.cron if "cron" in agent.surfaces else None,
        limits=t.limits,
        filesystem=t.filesystem,
        thresholds=t.evals.thresholds,
        regression_tolerance=t.evals.regression_tolerance,
    )


def load_spec(name: str) -> Spec:
    return materialize(store().load(name), load_org())
