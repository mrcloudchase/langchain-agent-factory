"""Org-level registries: approved tools, model tiers, and teams.

The registry is the organization's side of the contract. A team's spec can only ask
for what is registered here, and only for what its team is allowed to use.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from agent_factory.paths import REGISTRY_DIR

RiskTier = Literal["low", "medium", "high"]
ToolScope = Literal["user", "service", "any"]


class ToolEntry(BaseModel):
    """One approved tool. `impl` is a dotted path to a LangChain tool object."""

    name: str
    description: str
    impl: str
    risk: RiskTier = "low"
    sensitive: bool = Field(default=False, description="Requires human approval before running")
    scope: ToolScope = Field(
        default="any",
        description="user: acts as a person (needs a user surface); service: acts as the org",
    )
    teams: list[str] = Field(default_factory=list, description="Teams allowed. Empty = everyone")
    owner: str = ""

    def allowed_for(self, team: str) -> bool:
        return not self.teams or team in self.teams


class ModelTier(BaseModel):
    name: str
    description: str
    model: str = Field(description="provider:model id, e.g. anthropic:claude-sonnet-5")
    fallback: str | None = None
    teams: list[str] = Field(default_factory=list)
    max_cost_tier: int = Field(default=1, ge=1, le=3)

    def allowed_for(self, team: str) -> bool:
        return not self.teams or team in self.teams


class Team(BaseModel):
    name: str
    display_name: str
    lead: str
    cost_center: str = ""


class Registry(BaseModel):
    tools: dict[str, ToolEntry]
    models: dict[str, ModelTier]
    teams: dict[str, Team]
    default_model_tier: str = "standard"

    def tool(self, name: str) -> ToolEntry | None:
        return self.tools.get(name)

    def model_tier(self, name: str) -> ModelTier | None:
        return self.models.get(name)

    def team(self, name: str) -> Team | None:
        return self.teams.get(name)


def _load_yaml(name: str) -> dict:
    path = REGISTRY_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"registry file missing: {path}")
    return yaml.safe_load(path.read_text()) or {}


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    tools_raw = _load_yaml("tools.yaml").get("tools", [])
    models_raw = _load_yaml("models.yaml")
    teams_raw = _load_yaml("teams.yaml").get("teams", [])
    tools = {t["name"]: ToolEntry.model_validate(t) for t in tools_raw}
    models = {m["name"]: ModelTier.model_validate(m) for m in models_raw.get("tiers", [])}
    teams = {t["name"]: Team.model_validate(t) for t in teams_raw}
    return Registry(
        tools=tools,
        models=models,
        teams=teams,
        default_model_tier=models_raw.get("default_tier", "standard"),
    )


def reset_registry_cache() -> None:
    load_registry.cache_clear()
