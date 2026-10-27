"""The shared harness: turn a validated spec into a runnable Deep Agent.

This is the single place where org policy becomes runtime behavior. Teams never call
`create_deep_agent` directly; they write a spec and the factory does the rest.
"""

from __future__ import annotations

import importlib
from typing import Any

from deepagents import FilesystemMiddleware, create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent_factory.middleware import org_middleware
from agent_factory.models import resolve_model
from agent_factory.policy import PolicyResult, check_spec
from agent_factory.registry import Registry, ToolEntry, load_registry
from agent_factory.spec import AgentSpec

ORG_PREAMBLE = """You are {display_name}, built by the {team} team on the shared agent factory.
Owner: {owner}. Purpose: {purpose}

Operating rules (set by the platform team, not negotiable):
- Only use the tools you have been given. If a task needs something else, say so plainly.
- Some tools pause for human approval. If a tool reports it was rejected, do not retry it.
- A tool result starting with BLOCKED_BY_POLICY means the action is not permitted for you.
- Be concise, cite the tool results you relied on, and never invent data you did not retrieve.
"""


class PolicyError(ValueError):
    def __init__(self, spec: AgentSpec, result: PolicyResult) -> None:
        self.result = result
        lines = [f"{v.rule}: {v.message}" for v in result.errors]
        super().__init__(f"spec '{spec.name}' violates policy:\n  " + "\n  ".join(lines))


def load_tool(entry: ToolEntry) -> BaseTool:
    """Import a registered tool by dotted path `module:attribute`."""
    module_name, _, attr = entry.impl.partition(":")
    module = importlib.import_module(module_name)
    tool = getattr(module, attr)
    if not isinstance(tool, BaseTool):
        raise TypeError(f"{entry.impl} is not a LangChain tool")
    if tool.name != entry.name:
        raise ValueError(f"registry name '{entry.name}' != tool name '{tool.name}' ({entry.impl})")
    return tool


def resolve_tools(names: list[str], registry: Registry) -> list[BaseTool]:
    tools = []
    for name in names:
        entry = registry.tool(name)
        if entry is None:
            raise KeyError(f"tool '{name}' not registered")
        tools.append(load_tool(entry))
    return tools


def system_prompt_for(spec: AgentSpec) -> str:
    return (
        ORG_PREAMBLE.format(
            display_name=spec.display_name,
            team=spec.team,
            owner=spec.owner,
            purpose=spec.purpose,
        )
        + "\n"
        + spec.load_instructions()
    )


def _filesystem_middleware(spec: AgentSpec) -> FilesystemMiddleware | None:
    if spec.filesystem == "scratch":
        return None  # Deep Agents default: full state-backed scratch filesystem
    if spec.filesystem == "read_only":
        return FilesystemMiddleware(tools=["ls", "read_file", "glob", "grep"])
    return FilesystemMiddleware(tools=["read_file"])  # minimum the middleware allows


def build_agent(
    spec: AgentSpec,
    *,
    model: BaseChatModel | None = None,
    checkpointer: Any = None,
    store: Any = None,
    registry: Registry | None = None,
    offline: bool | None = None,
    enforce_policy: bool = True,
):
    """Build a compiled LangGraph agent from a spec, applying org policy and middleware."""
    reg = registry or load_registry()
    result = check_spec(spec, reg)
    if enforce_policy and not result.ok:
        raise PolicyError(spec, result)

    tools = resolve_tools(spec.tools, reg)
    model = model or resolve_model(spec.model_tier, dataset_path=spec.dataset_path, offline=offline)

    subagents = []
    for sub in spec.subagents:
        sub_model = model
        if sub.model_tier and sub.model_tier != spec.model_tier:
            sub_model = resolve_model(
                sub.model_tier, dataset_path=spec.dataset_path, offline=offline
            )
        subagents.append(
            {
                "name": sub.name,
                "description": sub.description,
                "system_prompt": sub.system_prompt,
                "tools": resolve_tools(sub.tools, reg),
                "model": sub_model,
                "middleware": org_middleware(
                    f"{spec.name}/{sub.name}", spec.team, set(sub.tools), spec.limits
                ),
            }
        )

    interrupt_on = {
        name: {"allowed_decisions": list(spec.oversight.allowed_decisions)}
        for name in spec.oversight.approve
    }

    middleware = org_middleware(spec.name, spec.team, set(spec.tools), spec.limits)
    fs = _filesystem_middleware(spec)
    if fs is not None:
        middleware = [fs, *middleware]  # name-matched override of the built-in

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt_for(spec),
        middleware=middleware,
        subagents=subagents or None,
        interrupt_on=interrupt_on or None,
        checkpointer=checkpointer,
        store=store,
        name=spec.name,
    )
