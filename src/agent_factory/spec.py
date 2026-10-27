"""The agent spec: the one file a team writes to get an agent from the factory.

A spec declares *what* an agent is for and *what it may touch*. The factory decides
*how* it is built, traced, limited, evaluated, and promoted. Everything here is
validated with Pydantic so a bad spec fails at load time, not in production.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from agent_factory.paths import agent_dir

SurfaceKind = Literal["slack", "mcp", "webhook", "cron", "chat", "sdk"]
Stage = Literal["dev", "staging", "production"]


class Surface(BaseModel):
    """Where an agent is embedded. Service surfaces act as the org; user surfaces as a person."""

    kind: SurfaceKind
    # Slack: channel name. Webhook: route path. Cron: schedule. MCP/chat/sdk: optional label.
    target: str | None = None
    schedule: str | None = None  # cron only, 5-field cron expression
    input_template: dict | None = None  # cron/webhook: input the surface sends to the agent

    @property
    def is_service(self) -> bool:
        """Service surfaces run without a human in the loop at request time."""
        return self.kind in ("webhook", "cron")


class Oversight(BaseModel):
    """Human-in-the-loop configuration. Sensitive registry tools must appear in `approve`."""

    approve: list[str] = Field(default_factory=list, description="Tools that pause for approval")
    allowed_decisions: list[Literal["approve", "edit", "reject"]] = Field(
        default_factory=lambda: ["approve", "reject"]
    )


class Limits(BaseModel):
    """Per-run budgets enforced by org middleware. Teams can tighten, never loosen past policy."""

    max_model_calls: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    max_tool_calls_per_tool: int | None = Field(default=None, ge=1)


class EvalThreshold(BaseModel):
    """Minimum mean score an evaluator must reach for promotion."""

    evaluator: str
    min_score: float = Field(ge=0.0, le=1.0)


class EvalConfig(BaseModel):
    dataset: str = "evals/dataset.jsonl"
    thresholds: list[EvalThreshold] = Field(default_factory=list)
    regression_tolerance: float = Field(
        default=0.05, ge=0.0, le=1.0, description="Max drop vs. baseline before the gate fails"
    )
    use_llm_judge: bool = False


class SubAgentSpec(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    model_tier: str | None = None


class AgentSpec(BaseModel):
    """Everything the factory needs to build, govern, evaluate, and place one agent."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    display_name: str
    team: str
    owner: str = Field(description="Accountable human, usually an email")
    purpose: str = Field(min_length=20)
    model_tier: str = "standard"
    instructions_file: str = "AGENTS.md"
    tools: list[str] = Field(default_factory=list)
    subagents: list[SubAgentSpec] = Field(default_factory=list)
    oversight: Oversight = Field(default_factory=Oversight)
    limits: Limits = Field(default_factory=Limits)
    surfaces: list[Surface] = Field(default_factory=list)
    evals: EvalConfig = Field(default_factory=EvalConfig)
    filesystem: Literal["none", "read_only", "scratch"] = "scratch"
    tags: list[str] = Field(default_factory=list)

    @field_validator("tools")
    @classmethod
    def _unique_tools(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate tool names in spec")
        return v

    @property
    def directory(self) -> Path:
        return agent_dir(self.name)

    @property
    def instructions_path(self) -> Path:
        return self.directory / self.instructions_file

    @property
    def dataset_path(self) -> Path:
        return self.directory / self.evals.dataset

    @property
    def baseline_path(self) -> Path:
        return self.directory / "evals" / "baseline.json"

    def load_instructions(self) -> str:
        if not self.instructions_path.exists():
            raise FileNotFoundError(f"{self.name}: missing {self.instructions_path}")
        return self.instructions_path.read_text()

    @property
    def is_service_agent(self) -> bool:
        return any(s.is_service for s in self.surfaces)


def load_spec(name_or_path: str | Path) -> AgentSpec:
    """Load a spec by agent name (agents/<name>/agent.yaml) or by explicit path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = agent_dir(str(name_or_path)) / "agent.yaml"
    if not path.exists():
        raise FileNotFoundError(f"spec not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    return AgentSpec.model_validate(data)


def list_specs() -> list[AgentSpec]:
    from agent_factory.paths import AGENTS_DIR

    specs = []
    if not AGENTS_DIR.exists():
        return specs
    for d in sorted(AGENTS_DIR.iterdir()):
        if (d / "agent.yaml").exists():
            specs.append(load_spec(d / "agent.yaml"))
    return specs
