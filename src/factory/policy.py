"""Policy: the rules an agent's choices must satisfy. Checked before anything is written.

Rules about the templates themselves live in `Org.problems`; these cover what a team chose.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.agents import Agent
from factory.org import Org


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str


def check(agent: Agent, org: Org) -> list[Violation]:
    out: list[Violation] = []

    def fail(rule: str, message: str) -> None:
        out.append(Violation(rule, message))

    if agent.template not in org.templates:
        fail("template.exists", f"unknown template '{agent.template}'")
        return out
    t = org.templates[agent.template]
    if agent.team not in org.teams:
        fail("team.exists", f"unknown team '{agent.team}'")
    if agent.team not in t.teams:
        fail("template.team", f"template '{t.key}' is not available to team '{agent.team}'")
    for name in agent.tools:
        if name not in t.tools.allowed:
            fail("tool.template", f"template '{t.key}' does not offer tool '{name}'")
        elif not org.tools[name].allows(agent.team):
            fail("tool.team", f"team '{agent.team}' may not use tool '{name}'")
    missing_defaults = [x for x in t.tools.default if x not in agent.tools]
    if t.archetype == "workflow" and missing_defaults:
        fail("tool.workflow", f"a workflow needs all of its step tools; missing {missing_defaults}")
    unattended = [s for s in agent.surfaces if s in ("webhook", "cron")]
    for surface in agent.surfaces:
        if surface not in t.surfaces.allowed:
            fail("surface.template", f"template '{t.key}' does not allow surface '{surface}'")
    for name in agent.tools:
        if unattended and name in org.tools and org.tools[name].acts_as == "user":
            fail(
                "surface.identity", f"'{name}' acts as a person and cannot run from {unattended[0]}"
            )
    for p in t.parameters:
        if p.required and not (agent.parameters.get(p.key) or p.default).strip():
            fail("parameter.required", f"'{p.label}' is required")
    return out
