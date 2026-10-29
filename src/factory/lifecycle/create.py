"""Create and reconfigure agents. Policy runs before anything is written."""

from __future__ import annotations

import copy

from factory.agents import Agent, store
from factory.org import Org, User, load_org
from factory.policy import Violation, check


class Refused(ValueError):
    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        super().__init__("; ".join(f"{v.rule}: {v.message}" for v in violations))


def draft(
    org: Org,
    by: User,
    *,
    name: str,
    template: str,
    team: str | None = None,
    display_name: str | None = None,
    purpose: str | None = None,
    parameters: dict[str, str] | None = None,
    tools: list[str] | None = None,
    surfaces: list[str] | None = None,
) -> Agent:
    """An unsaved agent with the template's defaults filled in for anything not chosen."""
    t = org.template(template)
    return Agent(
        name=name,
        display_name=display_name or name.replace("_", " ").title(),
        template=t.key,
        team=team or by.team,
        owner=by.id,
        purpose=purpose or t.summary,
        parameters={**t.parameter_defaults, **(parameters or {})},
        tools=list(tools if tools is not None else t.tools.default),
        surfaces=list(surfaces if surfaces is not None else t.surfaces.default),
        created_by=by.id,
    )


def review(org: Org, by: User, agent: Agent) -> list[Violation]:
    violations = check(agent, org)
    if not by.can_build_for(agent.team):
        violations.append(
            Violation("role.team", f"{by.name} cannot build agents for team '{agent.team}'")
        )
    if store().exists(agent.name):
        violations.append(Violation("name.taken", f"an agent named '{agent.name}' already exists"))
    return violations


def user_case(agent: str, index: int, question: str, must_contain: list[str]) -> dict:
    """A case written by a person. It has no recorded trajectory, so it runs live only."""
    return {
        "id": f"{agent}-user-{index:03d}",
        "inputs": {"question": question},
        "outputs": {"must_contain": must_contain},
        "metadata": {"split": "user"},
    }


def create(by: User, *, examples: list[dict] | None = None, **choices) -> Agent:
    org = load_org()
    agent = draft(org, by, **choices)
    if violations := review(org, by, agent):
        raise Refused(violations)
    s = store()
    s.save(agent)
    cases = copy.deepcopy(org.template(agent.template).examples)
    cases += [
        user_case(agent.name, i, e["question"], e.get("must_contain", []))
        for i, e in enumerate(examples or [], 1)
    ]
    s.write_dataset(agent.name, cases)
    return agent


def reconfigure(by: User, name: str, parameters: dict[str, str]) -> Agent:
    """Change parameter values. The template owns everything else."""
    s = store()
    agent = s.load(name)
    if not by.can_build_for(agent.team):
        raise Refused(
            [Violation("role.team", f"{by.name} cannot change agents for team '{agent.team}'")]
        )
    updated = agent.model_copy(update={"parameters": {**agent.parameters, **parameters}})
    if violations := check(updated, load_org()):
        raise Refused(violations)
    s.save(updated)
    return updated
