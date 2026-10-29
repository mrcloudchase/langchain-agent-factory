"""The organization: teams, users, model tiers, the tool catalog, processes, and templates.

`load_org` reads everything under org/. `Org.problems` checks it as a whole, which is what the
platform team runs in CI before a change to org/ merges.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from factory import config
from factory.templates import Template, load_templates

Role = Literal["platform", "builder", "approver", "viewer"]
Check = Literal["policy", "evals"]
ApprovalKind = Literal["team", "platform"]


class Team(BaseModel):
    name: str
    display_name: str


class User(BaseModel):
    id: str
    name: str
    title: str
    role: Role
    team: str

    def can_build_for(self, team: str) -> bool:
        return self.role == "platform" or (
            self.role in ("builder", "approver") and self.team == team
        )

    def can_approve(self, kind: ApprovalKind, team: str) -> bool:
        if kind == "platform":
            return self.role == "platform"
        return self.role == "approver" and self.team == team


class Tier(BaseModel):
    name: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    teams: list[str] = Field(default_factory=list)

    def allows(self, team: str) -> bool:
        return not self.teams or team in self.teams


class Tool(BaseModel):
    name: str
    impl: str
    description: str
    owner: str
    teams: list[str] = Field(default_factory=list)
    sensitive: bool = False
    acts_as: Literal["any", "user"] = "any"

    def allows(self, team: str) -> bool:
        return not self.teams or team in self.teams


class Transition(BaseModel):
    checks: list[Check]
    approvals: list[ApprovalKind] = Field(default_factory=list)


class Process(BaseModel):
    name: str
    description: str
    stages: list[str]
    transitions: dict[str, Transition]

    @model_validator(mode="after")
    def _invariants(self) -> Process:
        assert len(self.stages) >= 2 and len(set(self.stages)) == len(self.stages)
        assert list(self.transitions) == self.stages[1:], (
            "one transition into each stage after the first"
        )
        return self

    def next_stage(self, current: str) -> str | None:
        i = self.stages.index(current)
        return self.stages[i + 1] if i + 1 < len(self.stages) else None


class Org(BaseModel):
    teams: dict[str, Team]
    users: dict[str, User]
    tiers: dict[str, Tier]
    tools: dict[str, Tool]
    processes: dict[str, Process]
    templates: dict[str, Template]

    def user(self, user_id: str | None) -> User | None:
        return self.users.get(user_id or "")

    def template(self, key: str) -> Template:
        if key not in self.templates:
            raise KeyError(f"unknown template '{key}'")
        return self.templates[key]

    def problems(self) -> list[str]:
        """Every cross-reference that does not resolve. Empty means the org is consistent."""
        from factory.evals.evaluators import EVALUATORS

        out = [
            f"user {u.id}: unknown team '{u.team}'"
            for u in self.users.values()
            if u.team not in self.teams
        ]
        for t in self.templates.values():
            where = f"template {t.key}"
            out += [f"{where}: unknown team '{x}'" for x in t.teams if x not in self.teams]
            if t.process not in self.processes:
                out.append(f"{where}: unknown process '{t.process}'")
            tier = self.tiers.get(t.model_tier)
            if tier is None:
                out.append(f"{where}: unknown model tier '{t.model_tier}'")
            else:
                out += [
                    f"{where}: tier '{tier.name}' is not available to team '{x}'"
                    for x in t.teams
                    if not tier.allows(x)
                ]
            for name in t.tools.allowed:
                tool = self.tools.get(name)
                if tool is None:
                    out.append(f"{where}: tool '{name}' is not in the catalog")
                elif tool.sensitive and name not in t.approvals:
                    out.append(f"{where}: sensitive tool '{name}' must be listed under approvals")
            out += [
                f"{where}: unknown evaluator '{k}'"
                for k in t.evals.thresholds
                if k not in EVALUATORS
            ]
        return out


def _yaml(name: str) -> dict:
    return yaml.safe_load((config.org_dir() / name).read_text())


@cache
def load_org() -> Org:
    people = _yaml("teams.yaml")
    processes = [
        Process.model_validate(yaml.safe_load(p.read_text()))
        for p in sorted((config.org_dir() / "processes").glob("*.yaml"))
    ]
    return Org(
        teams={t["name"]: Team.model_validate(t) for t in people["teams"]},
        users={u["id"]: User.model_validate(u) for u in people["users"]},
        tiers={t["name"]: Tier.model_validate(t) for t in _yaml("models.yaml")["tiers"]},
        tools={t["name"]: Tool.model_validate(t) for t in _yaml("tools.yaml")["tools"]},
        processes={p.name: p for p in processes},
        templates=load_templates(config.org_dir() / "templates"),
    )
