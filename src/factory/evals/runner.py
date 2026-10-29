"""Run a built graph on one request and record what happened.

Approvals are auto-approved and recorded, so evaluators can check that the agent paused when it
should have (and only then).
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from factory.build.middleware import BLOCKED_PREFIX
from factory.build.models import text_of

MAX_RESUMES = 5


def trajectory(messages: list) -> dict[str, Any]:
    tool_calls = [tc["name"] for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls]
    blocked = [
        m.name
        for m in messages
        if isinstance(m, ToolMessage) and text_of(m.content).startswith(BLOCKED_PREFIX)
    ]
    answers = [
        text_of(m.content)
        for m in messages
        if isinstance(m, AIMessage) and text_of(m.content).strip()
    ]
    return {"tool_calls": tool_calls, "blocked": blocked, "answer": answers[-1] if answers else ""}


def run(graph, question: str, *, approve: bool = True) -> dict[str, Any]:
    config = {"configurable": {"thread_id": f"eval-{uuid.uuid4()}"}}
    state = graph.invoke({"messages": [HumanMessage(content=question)]}, config=config)
    approvals: list[str] = []
    for _ in range(MAX_RESUMES):
        if not state.get("__interrupt__"):
            break
        requests = state["__interrupt__"][0].value["action_requests"]
        approvals += [r["name"] for r in requests]
        decision = {"type": "approve"} if approve else {"type": "reject", "message": "Rejected."}
        state = graph.invoke(
            Command(resume={"decisions": [decision] * len(requests)}), config=config
        )
    return {**trajectory(state["messages"]), "approvals": approvals}
