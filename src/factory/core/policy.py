"""Policy: the rules every generated spec must satisfy. Violations are data."""

from __future__ import annotations

from dataclasses import dataclass, field

from factory.core.registry import Registry, load_registry
from factory.core.spec import AgentSpec
from factory.core.template import Template, load_template


@dataclass
class Violation:
    rule: str
    message: str
    severity: str = "error"


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

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [{"rule": v.rule, "message": v.message} for v in self.errors],
            "warnings": [{"rule": v.rule, "message": v.message} for v in self.warnings],
        }


def check_spec(
    spec: AgentSpec,
    registry: Registry | None = None,
    template: Template | None = None,
    *,
    require_files: bool = True,
) -> PolicyResult:
    reg = registry or load_registry()
    t = template or load_template(spec.template)
    out = PolicyResult()
    sev = reg.policy.severity

    def add(rule: str, message: str, default: str = "error") -> None:
        out.violations.append(Violation(rule, message, sev.get(rule, default)))

    # Ownership
    if reg.team(spec.team) is None:
        add("team.exists", f"team '{spec.team}' is not in org/teams.yaml")
    if not t.allowed_for(spec.team):
        add("template.allowed", f"template '{t.key}' is not available to team '{spec.team}'")
    if reg.process(spec.process) is None:
        add("process.exists", f"process '{spec.process}' is not in org/processes/")

    # Model tier
    tier = reg.model_tier(spec.model_tier)
    if tier is None:
        add("model.exists", f"model tier '{spec.model_tier}' is not registered")
    elif not tier.allowed_for(spec.team):
        add("model.allowed", f"team '{spec.team}' may not use tier '{spec.model_tier}'")

    # Tools
    all_tools = (
        list(spec.tools)
        + [x for s in spec.subagents for x in s.tools]
        + [x for st in spec.steps for x in st.tools]
    )
    for name in all_tools:
        entry = reg.tool(name)
        if entry is None:
            add("tool.exists", f"tool '{name}' is not in the published catalog")
            continue
        if not entry.allowed_for(spec.team):
            add("tool.allowed", f"team '{spec.team}' may not use tool '{name}'")
        # A template's allowed list bounds what an instance may add; an empty list means
        # "only the defaults", so a template with no tools allows none.
        template_allowed = t.tools.allowed or t.tools.default
        if name in spec.tools and name not in template_allowed:
            add("tool.template", f"template '{t.key}' does not allow tool '{name}'")
        if entry.sensitive and name not in spec.oversight.approve:
            add("oversight.sensitive", f"tool '{name}' is sensitive and must pause for approval")
        if entry.scope == "user" and spec.is_service_agent:
            add(
                "surface.identity",
                f"tool '{name}' acts as a user, but a webhook/cron surface runs unattended",
            )
        if entry.risk == "high" and spec.is_service_agent:
            add(
                "surface.high_risk",
                f"high-risk tool '{name}' is reachable from an unattended surface",
                "warning",
            )

    for name in t.oversight.required_approve:
        if name not in spec.oversight.approve:
            add("oversight.required", f"template requires approval on '{name}'")
    for name in spec.oversight.approve:
        if name not in all_tools:
            add("oversight.unknown", f"approval listed for unknown tool '{name}'")

    # Surfaces
    for s in spec.surfaces:
        if t.surfaces.allowed and s.kind not in t.surfaces.allowed:
            add("surface.template", f"template '{t.key}' does not allow surface '{s.kind}'")
    if not spec.surfaces:
        add("surfaces.none", "agent declares no surfaces; reachable only via SDK", "warning")

    # Limits
    for key, ceiling in reg.policy.ceilings.items():
        val = getattr(spec.limits, key, None)
        if val is not None and val > ceiling:
            add("limits.ceiling", f"{key}={val} exceeds the org ceiling {ceiling}")

    # Parameters
    for p in t.parameters:
        if p.required and spec.parameters.get(p.key) in (None, ""):
            add("parameters.required", f"parameter '{p.key}' is required")

    # Evals and files
    if not spec.evals.thresholds:
        add("evals.required", "template must declare at least one eval threshold")
    if require_files and not spec.dataset_path.exists():
        add("evals.dataset", f"eval dataset missing: {spec.dataset_path}")
    if spec.archetype == "workflow" and not spec.steps:
        add("workflow.steps", "workflow template has no steps")
    if spec.archetype == "agent" and not spec.instructions.strip():
        add("instructions.exists", "agent template has no instructions")
    return out
