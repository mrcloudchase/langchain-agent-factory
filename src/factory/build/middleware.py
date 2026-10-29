"""Middleware every agent gets. Teams cannot remove it.

- Limits: model and tool calls per run.
- ToolAllowlist: refuses any tool outside the agent's approved set at call time. The model only
  sees approved tools at build time; this is defense in depth against invented tool names.
- Audit: one structured log line per tool call.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage

from factory.templates import Limits

audit_log = logging.getLogger("factory.audit")
BLOCKED_PREFIX = "BLOCKED_BY_POLICY"
# Built into Deep Agents; harmless (state-backed files, delegation, planning).
BUILTIN_TOOLS = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "task", "write_todos"}
)


class ToolAllowlist(AgentMiddleware):
    def __init__(self, agent: str, allowed: set[str]) -> None:
        super().__init__()
        self.agent = agent
        self.allowed = frozenset(allowed) | BUILTIN_TOOLS

    def _refuse(self, request: ToolCallRequest) -> ToolMessage:
        name = request.tool_call["name"]
        audit_log.warning(json.dumps({"event": "tool_blocked", "agent": self.agent, "tool": name}))
        return ToolMessage(
            content=(
                f"{BLOCKED_PREFIX}: '{name}' is not approved for {self.agent}. Do not retry it."
            ),
            tool_call_id=request.tool_call["id"],
            name=name,
            status="error",
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable) -> ToolMessage:
        return (
            handler(request) if request.tool_call["name"] in self.allowed else self._refuse(request)
        )

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[..., Awaitable]
    ) -> ToolMessage:
        if request.tool_call["name"] not in self.allowed:
            return self._refuse(request)
        return await handler(request)


class Audit(AgentMiddleware):
    def __init__(self, agent: str, team: str) -> None:
        super().__init__()
        self.agent = agent
        self.team = team

    def _log(self, request: ToolCallRequest, started: float, result) -> None:
        ok = not (isinstance(result, ToolMessage) and result.status == "error")
        audit_log.info(
            json.dumps(
                {
                    "event": "tool_call",
                    "agent": self.agent,
                    "team": self.team,
                    "tool": request.tool_call["name"],
                    "ok": ok,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable) -> ToolMessage:
        started = time.perf_counter()
        result = handler(request)
        self._log(request, started, result)
        return result

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[..., Awaitable]
    ) -> ToolMessage:
        started = time.perf_counter()
        result = await handler(request)
        self._log(request, started, result)
        return result


def org_middleware(
    agent: str, team: str, tools: list[str], limits: Limits
) -> list[AgentMiddleware]:
    return [
        ModelCallLimitMiddleware(run_limit=limits.model_calls, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=limits.tool_calls, exit_behavior="continue"),
        ToolAllowlist(agent, set(tools)),
        Audit(agent, team),
    ]
