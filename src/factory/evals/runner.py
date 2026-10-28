"""Run an agent against one example and return a structured trajectory.

The target auto-approves human-in-the-loop interrupts and records that they happened,
so evaluators can check that sensitive actions paused (and that harmless ones did not).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from factory.build import build as build_agent
from factory.build.middleware import BLOCKED_PREFIX
from factory.core.spec import AgentSpec

MAX_RESUMES = 4


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content)


def summarize_trajectory(messages: list) -> dict[str, Any]:
    tool_calls: list[str] = []
    blocked: list[str] = []
    answer = ""
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                tool_calls.append(tc["name"])
            if _text(m.content).strip():
                answer = _text(m.content)
        elif isinstance(m, ToolMessage) and _text(m.content).startswith(BLOCKED_PREFIX):
            blocked.append(m.name or "?")
    return {"answer": answer, "tool_calls": tool_calls, "blocked": blocked}


def run_once(agent, question: str, *, approve: bool = True) -> dict[str, Any]:
    """Invoke an agent on a question, auto-resolving interrupts. Returns a trajectory dict."""
    config = {"configurable": {"thread_id": f"eval-{uuid.uuid4()}"}}
    state = agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)
    interrupts: list[str] = []
    resumes = 0
    while state.get("__interrupt__") and resumes < MAX_RESUMES:
        payload = state["__interrupt__"][0].value
        requests = payload.get("action_requests", [])
        interrupts.extend(r["name"] for r in requests)
        decision = (
            {"type": "approve"} if approve else {"type": "reject", "message": "Rejected in eval."}
        )
        state = agent.invoke(
            Command(resume={"decisions": [decision for _ in requests]}), config=config
        )
        resumes += 1
    out = summarize_trajectory(state["messages"])
    out["interrupts"] = interrupts
    out["resumed"] = resumes
    return out


def make_target(
    spec: AgentSpec, *, model=None, offline: bool | None = None
) -> Callable[[dict], dict]:
    """Build the agent once; each example runs on its own thread."""
    agent = build_agent(spec, model=model, checkpointer=InMemorySaver(), offline=offline)

    def target(inputs: dict) -> dict:
        return run_once(agent, inputs["question"])

    target.__name__ = spec.name
    return target
