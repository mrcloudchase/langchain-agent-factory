"""Agent archetype: the model chooses the steps. Built on Deep Agents."""

from __future__ import annotations

from typing import Any

from deepagents import FilesystemMiddleware, create_deep_agent
from langchain_core.language_models import BaseChatModel

from factory.build.middleware import org_middleware
from factory.build.tools import load_tools
from factory.spec import Spec

PREAMBLE = """You are {display_name}, built by the {team} team on the organization's agent factory.
Owner: {owner}. Purpose: {purpose}

Rules set by the platform team:
- Use only the tools you have. If a task needs something else, say so plainly.
- Some tools pause for human approval. If a tool reports it was rejected, do not retry it.
- A result starting with BLOCKED_BY_POLICY means the action is not permitted.
- Be concise, cite the tool results you relied on, and never invent data you did not retrieve.
"""

_FILESYSTEM_TOOLS = {"read_only": ["ls", "read_file", "glob", "grep"], "none": ["read_file"]}


def system_prompt(spec: Spec) -> str:
    return (
        PREAMBLE.format(**spec.model_dump(include={"display_name", "team", "owner", "purpose"}))
        + "\n"
        + spec.instructions
    )


def build_agent(spec: Spec, model: BaseChatModel, checkpointer: Any = None):
    middleware = org_middleware(spec.name, spec.team, spec.tools, spec.limits)
    if spec.filesystem in _FILESYSTEM_TOOLS:
        middleware = [FilesystemMiddleware(tools=_FILESYSTEM_TOOLS[spec.filesystem]), *middleware]
    return create_deep_agent(
        model=model,
        tools=load_tools(spec.tools),
        system_prompt=system_prompt(spec),
        middleware=middleware,
        interrupt_on={name: True for name in spec.approvals} or None,
        checkpointer=checkpointer,
        name=spec.name,
    )
