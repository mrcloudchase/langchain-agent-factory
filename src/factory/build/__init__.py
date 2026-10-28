"""Build layer: turn a generated spec into a runnable graph, by archetype."""

from __future__ import annotations

from typing import Any

from factory.core.spec import AgentSpec


def build(
    spec: AgentSpec,
    *,
    model=None,
    checkpointer: Any = None,
    store: Any = None,
    offline: bool | None = None,
    enforce_policy: bool = True,
):
    from factory.core.policy import check_spec

    if enforce_policy:
        result = check_spec(spec)
        if not result.ok:
            raise PolicyError(spec, result)
    if spec.archetype == "workflow":
        from factory.build.workflow_compiler import compile_workflow

        return compile_workflow(spec, model=model, checkpointer=checkpointer, offline=offline)
    from factory.build.agent_harness import build_agent

    return build_agent(spec, model=model, checkpointer=checkpointer, store=store, offline=offline)


class PolicyError(ValueError):
    def __init__(self, spec: AgentSpec, result) -> None:
        self.result = result
        lines = [f"{v.rule}: {v.message}" for v in result.errors]
        super().__init__(f"'{spec.name}' violates policy:\n  " + "\n  ".join(lines))
