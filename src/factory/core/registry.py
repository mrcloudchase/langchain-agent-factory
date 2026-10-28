"""The organization's registry: teams, users, model tiers, tools, policy settings, processes."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from factory.paths import ORG_DIR, PROCESSES_DIR

RiskTier = Literal["low", "medium", "high"]
ToolScope = Literal["user", "service", "any"]
Role = Literal["platform", "builder", "approver", "viewer"]


class ToolEntry(BaseModel):
    name: str
    description: str
    impl: str
    risk: RiskTier = "low"
    sensitive: bool = False
    scope: ToolScope = "any"
    teams: list[str] = Field(default_factory=list)
    owner: str = ""

    def allowed_for(self, team: str) -> bool:
        return not self.teams or team in self.teams


class ModelTier(BaseModel):
    name: str
    description: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    fallback: str | None = None
    teams: list[str] = Field(default_factory=list)
    max_cost_tier: int = 1

    def allowed_for(self, team: str) -> bool:
        return not self.teams or team in self.teams


class Team(BaseModel):
    name: str
    display_name: str
    lead: str
    cost_center: str = ""


class User(BaseModel):
    id: str
    name: str
    role: Role
    team: str


class Transition(BaseModel):
    from_stage: str = Field(alias="from")
    to: str
    gates: list[str]
    approver_role: str | None = None
    budget: dict[str, int] = Field(default_factory=dict)
    freeze_dataset: bool = False

    model_config = {"populate_by_name": True}


class Process(BaseModel):
    name: str
    description: str = ""
    stages: list[str]
    transitions: list[Transition]

    def transition(self, to: str) -> Transition | None:
        return next((t for t in self.transitions if t.to == to), None)

    def next_stage(self, current: str | None) -> str | None:
        if current is None:
            return self.stages[1] if len(self.stages) > 1 else None
        i = self.stages.index(current)
        return self.stages[i + 1] if i + 1 < len(self.stages) else None


class PolicySettings(BaseModel):
    severity: dict[str, str] = Field(default_factory=dict)
    ceilings: dict[str, int] = Field(default_factory=dict)


class Registry(BaseModel):
    teams: dict[str, Team]
    users: dict[str, User]
    models: dict[str, ModelTier]
    default_model_tier: str
    tools: dict[str, ToolEntry]
    processes: dict[str, Process]
    policy: PolicySettings

    def tool(self, name: str) -> ToolEntry | None:
        return self.tools.get(name)

    def model_tier(self, name: str) -> ModelTier | None:
        return self.models.get(name)

    def team(self, name: str) -> Team | None:
        return self.teams.get(name)

    def process(self, name: str) -> Process | None:
        return self.processes.get(name)

    def user(self, user_id: str | None) -> User | None:
        return self.users.get(user_id or "")

    def approvers_for(self, team: str, role: str = "approver") -> list[User]:
        return [u for u in self.users.values() if u.role == role and u.team == team]


def _yaml(path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    teams_raw = _yaml(ORG_DIR / "teams.yaml")
    models_raw = _yaml(ORG_DIR / "models.yaml")
    tools_raw = _yaml(ORG_DIR / "tools" / "catalog.yaml")
    policy_raw = _yaml(ORG_DIR / "policy.yaml")
    processes = {}
    for p in sorted(PROCESSES_DIR.glob("*.yaml")):
        proc = Process.model_validate(_yaml(p))
        processes[proc.name] = proc
    return Registry(
        teams={t["name"]: Team.model_validate(t) for t in teams_raw.get("teams", [])},
        users={u["id"]: User.model_validate(u) for u in teams_raw.get("users", [])},
        models={m["name"]: ModelTier.model_validate(m) for m in models_raw.get("tiers", [])},
        default_model_tier=models_raw.get("default_tier", "standard"),
        tools={t["name"]: ToolEntry.model_validate(t) for t in tools_raw.get("tools", [])},
        processes=processes,
        policy=PolicySettings.model_validate(policy_raw),
    )


def reset_registry_cache() -> None:
    load_registry.cache_clear()
