"""Agent archetype: a Deep Agent with the organization's middleware."""

from __future__ import annotations

import importlib
from typing import Any

from deepagents import FilesystemMiddleware, create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from factory.build.middleware import org_middleware
from factory.build.models import resolve_model
from factory.core.instance import read_dataset
from factory.core.registry import Registry, ToolEntry, load_registry
from factory.core.spec import AgentSpec

ORG_PREAMBLE = """You are {display_name}, built by the {team} team on the agent factory.
Owner: {owner}. Purpose: {purpose}

Operating rules (set by the platform team):
- Only use the tools you have been given. If a task needs something else, say so plainly.
- Some tools pause for human approval. If a tool reports it was rejected, do not retry it.
- A tool result starting with BLOCKED_BY_POLICY means the action is not permitted for you.
- Be concise, cite the tool results you relied on, and never invent data you did not retrieve.
"""


def load_tool(entry: ToolEntry) -> BaseTool:
    module_name, _, attr = entry.impl.partition(":")
    tool = getattr(importlib.import_module(module_name), attr)
    if not isinstance(tool, BaseTool):
        raise TypeError(f"{entry.impl} is not a LangChain tool")
    if tool.name != entry.name:
        raise ValueError(f"catalog name '{entry.name}' != tool name '{tool.name}'")
    return tool


def resolve_tools(names: list[str], registry: Registry) -> list[BaseTool]:
    out = []
    for n in names:
        entry = registry.tool(n)
        if entry is None:
            raise KeyError(f"tool '{n}' not in catalog")
        out.append(load_tool(entry))
    return out


def system_prompt_for(spec: AgentSpec) -> str:
    return (
        ORG_PREAMBLE.format(
            display_name=spec.display_name, team=spec.team, owner=spec.owner, purpose=spec.purpose
        )
        + "\n"
        + spec.instructions
    )


def _dataset_rows(spec: AgentSpec):
    from factory.core.instance import Instance

    try:
        return read_dataset(Instance.model_construct(name=spec.name))
    except Exception:  # noqa: BLE001
        return []


def _fs(spec: AgentSpec):
    if spec.filesystem == "scratch":
        return None
    if spec.filesystem == "read_only":
        return FilesystemMiddleware(tools=["ls", "read_file", "glob", "grep"])
    return FilesystemMiddleware(tools=["read_file"])


def build_agent(
    spec: AgentSpec,
    *,
    model: BaseChatModel | None = None,
    checkpointer: Any = None,
    store: Any = None,
    offline: bool | None = None,
):
    reg = load_registry()
    rows = _dataset_rows(spec)
    model = model or resolve_model(spec.model_tier, rows=rows, offline=offline)
    subagents = []
    for sub in spec.subagents:
        sub_model = model
        if sub.model_tier and sub.model_tier != spec.model_tier:
            sub_model = resolve_model(sub.model_tier, rows=rows, offline=offline)
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
        n: {"allowed_decisions": list(spec.oversight.allowed_decisions)}
        for n in spec.oversight.approve
    }
    middleware = org_middleware(spec.name, spec.team, set(spec.tools), spec.limits)
    fs = _fs(spec)
    if fs is not None:
        middleware = [fs, *middleware]
    return create_deep_agent(
        model=model,
        tools=resolve_tools(spec.tools, reg),
        system_prompt=system_prompt_for(spec),
        middleware=middleware,
        subagents=subagents or None,
        interrupt_on=interrupt_on or None,
        checkpointer=checkpointer,
        store=store,
        name=spec.name,
    )
