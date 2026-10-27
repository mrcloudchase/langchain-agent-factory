"""Policy: the rules every spec must satisfy before the factory will build it.

Violations are data, not exceptions, so the CLI, CI, and tests can all render them.
Each rule maps to a governance question a platform team actually gets asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_factory.registry import Registry, load_registry
from agent_factory.spec import AgentSpec


@dataclass
class Violation:
    rule: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class PolicyResult:
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "warning"]


def check_spec(spec: AgentSpec, registry: Registry | None = None) -> PolicyResult:
    """Validate a spec against the org registry. Pure function, no side effects."""
    reg = registry or load_registry()
    out = PolicyResult()
    add = out.violations.append

    # 1. The owning team must exist. Nobody ships an orphan agent.
    if reg.team(spec.team) is None:
        add(Violation("team.exists", f"team '{spec.team}' is not in registry/teams.yaml"))

    # 2. Model tier must exist and be allowed for the team.
    tier = reg.model_tier(spec.model_tier)
    if tier is None:
        add(Violation("model.exists", f"model tier '{spec.model_tier}' is not registered"))
    elif not tier.allowed_for(spec.team):
        add(Violation("model.allowed", f"team '{spec.team}' may not use tier '{spec.model_tier}'"))

    # 3. Every tool must be registered and allowed for the team.
    all_tool_names = list(spec.tools) + [t for s in spec.subagents for t in s.tools]
    for tool_name in all_tool_names:
        entry = reg.tool(tool_name)
        if entry is None:
            add(Violation("tool.exists", f"tool '{tool_name}' is not in registry/tools.yaml"))
            continue
        if not entry.allowed_for(spec.team):
            add(Violation("tool.allowed", f"team '{spec.team}' may not use tool '{tool_name}'"))

        # 4. Sensitive tools must be gated by human approval.
        if entry.sensitive and tool_name not in spec.oversight.approve:
            add(
                Violation(
                    "oversight.sensitive",
                    f"tool '{tool_name}' is sensitive and must be listed under oversight.approve",
                )
            )

        # 5. Surface/identity rule: a service surface cannot use user-scoped tools,
        #    and a user-scoped tool needs a surface that carries a user identity.
        if entry.scope == "user" and spec.is_service_agent:
            add(
                Violation(
                    "surface.identity",
                    f"tool '{tool_name}' acts as a user, but a webhook/cron surface runs as "
                    "a service with no user identity",
                )
            )

    # 6. Approval list must only reference tools the agent actually has.
    for name in spec.oversight.approve:
        if name not in all_tool_names:
            add(Violation("oversight.unknown", f"oversight.approve lists unknown tool '{name}'"))

    # 7. Every agent must declare an eval gate. No evals, no promotion.
    if not spec.evals.thresholds:
        add(Violation("evals.required", "spec must declare at least one eval threshold"))
    if not spec.dataset_path.exists():
        add(Violation("evals.dataset", f"eval dataset missing: {spec.dataset_path}"))

    # 8. Instructions file must exist.
    if not spec.instructions_path.exists():
        add(Violation("instructions.exists", f"missing {spec.instructions_path}"))

    # 9. Advisory: high-risk tools on service surfaces deserve a second look.
    for tool_name in spec.tools:
        entry = reg.tool(tool_name)
        if entry and entry.risk == "high" and spec.is_service_agent:
            add(
                Violation(
                    "surface.high_risk",
                    f"high-risk tool '{tool_name}' is reachable from an unattended surface",
                    severity="warning",
                )
            )

    # 10. Advisory: an agent with no surfaces is not embedded anywhere.
    if not spec.surfaces:
        add(
            Violation(
                "surfaces.none",
                "agent declares no surfaces; it will only be reachable via SDK",
                severity="warning",
            )
        )

    return out
