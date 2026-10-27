"""Organization-owned middleware. Every factory agent gets this stack; teams cannot remove it.

- Budget: model-call and tool-call limits per run (cost and runaway protection).
- Allowlist: defense in depth. The model only sees approved tools at build time, and this
  hook refuses anything else at call time, so a prompt-injected or hallucinated tool
  name cannot execute.
- Audit: a structured log line per tool call, carrying agent, team, tool, and outcome,
  which is what a platform team greps when something goes wrong.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage

audit_log = logging.getLogger("agent_factory.audit")

# Tools Deep Agents provides itself. These are harmless (state-backed filesystem,
# subagent delegation) and are always allowed.
BUILTIN_TOOLS = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
        "task",
        "write_todos",
    }
)

BLOCKED_PREFIX = "BLOCKED_BY_POLICY"


class ToolAllowlistMiddleware(AgentMiddleware):
    """Refuse tool calls that are not on the agent's approved list."""

    def __init__(self, agent_name: str, allowed: set[str]) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.allowed = set(allowed) | BUILTIN_TOOLS

    def _block(self, request: ToolCallRequest) -> ToolMessage:
        name = request.tool_call["name"]
        audit_log.warning(
            json.dumps({"event": "tool_blocked", "agent": self.agent_name, "tool": name})
        )
        return ToolMessage(
            content=f"{BLOCKED_PREFIX}: tool '{name}' is not approved for agent "
            f"'{self.agent_name}'. Do not retry it; explain the limitation to the user.",
            tool_call_id=request.tool_call["id"],
            name=name,
            status="error",
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable) -> Any:
        if request.tool_call["name"] not in self.allowed:
            return self._block(request)
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable) -> Any:
        if request.tool_call["name"] not in self.allowed:
            return self._block(request)
        return await handler(request)


class AuditMiddleware(AgentMiddleware):
    """Emit one structured audit record per tool call."""

    def __init__(self, agent_name: str, team: str) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.team = team

    def _record(self, request: ToolCallRequest, started: float, ok: bool, err: str | None = None):
        audit_log.info(
            json.dumps(
                {
                    "event": "tool_call",
                    "agent": self.agent_name,
                    "team": self.team,
                    "tool": request.tool_call["name"],
                    "arg_keys": sorted((request.tool_call.get("args") or {}).keys()),
                    "ok": ok,
                    "error": err,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable) -> Any:
        started = time.perf_counter()
        try:
            result = handler(request)
        except Exception as e:  # noqa: BLE001
            self._record(request, started, False, repr(e))
            raise
        ok = not (isinstance(result, ToolMessage) and result.status == "error")
        self._record(request, started, ok)
        return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable) -> Any:
        started = time.perf_counter()
        try:
            result = await handler(request)
        except Exception as e:  # noqa: BLE001
            self._record(request, started, False, repr(e))
            raise
        ok = not (isinstance(result, ToolMessage) and result.status == "error")
        self._record(request, started, ok)
        return result


def org_middleware(
    agent_name: str, team: str, allowed_tools: set[str], limits
) -> list[AgentMiddleware]:
    """The non-negotiable stack, in execution order."""
    stack: list[AgentMiddleware] = [
        ModelCallLimitMiddleware(run_limit=limits.max_model_calls, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=limits.max_tool_calls, exit_behavior="continue"),
        ToolAllowlistMiddleware(agent_name, allowed_tools),
        AuditMiddleware(agent_name, team),
    ]
    if limits.max_tool_calls_per_tool:
        for name in sorted(allowed_tools):
            stack.append(
                ToolCallLimitMiddleware(
                    tool_name=name,
                    run_limit=limits.max_tool_calls_per_tool,
                    exit_behavior="continue",
                )
            )
    return stack
