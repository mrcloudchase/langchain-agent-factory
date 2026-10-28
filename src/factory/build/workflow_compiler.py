"""Workflow archetype: fixed steps compiled to a LangGraph graph.

Each step is a bounded model call. Steps with tools run a small `create_agent` loop limited
to those tools, with the organization's middleware and human-in-the-loop on sensitive ones.
The model works inside a step; it never chooses the steps.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from factory.build.agent_harness import ORG_PREAMBLE, _dataset_rows, resolve_tools
from factory.build.middleware import org_middleware
from factory.build.models import _text, resolve_model
from factory.core.registry import load_registry
from factory.core.spec import AgentSpec, Step, render


class WorkflowState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    question: str
    outputs: dict[str, str]


def _skip(step: Step, outputs: dict[str, str]) -> bool:
    if not step.skip_unless:
        return False
    text = outputs.get(step.skip_unless.get("output", ""), "")
    return step.skip_unless.get("contains", "") not in text


def compile_workflow(
    spec: AgentSpec,
    *,
    model: BaseChatModel | None = None,
    checkpointer: Any = None,
    offline: bool | None = None,
):
    reg = load_registry()
    rows = _dataset_rows(spec)
    model = model or resolve_model(spec.model_tier, rows=rows, offline=offline)
    preamble = ORG_PREAMBLE.format(
        display_name=spec.display_name, team=spec.team, owner=spec.owner, purpose=spec.purpose
    )
    graph = StateGraph(WorkflowState)

    def start(state: WorkflowState) -> dict[str, Any]:
        q = state.get("question")
        if not q:
            human = next(
                (m for m in state.get("messages", []) if isinstance(m, HumanMessage)), None
            )
            q = _text(human.content) if human else ""
        return {"question": q, "outputs": dict(state.get("outputs") or {})}

    graph.add_node("start", start)

    def make_node(step: Step):
        tools = resolve_tools(step.tools, reg)
        middleware = list(
            org_middleware(f"{spec.name}/{step.key}", spec.team, set(step.tools), spec.limits)
        )
        gated = [t for t in step.tools if t in spec.oversight.approve]
        if gated:
            middleware.append(
                HumanInTheLoopMiddleware(
                    {
                        t: {"allowed_decisions": list(spec.oversight.allowed_decisions)}
                        for t in gated
                    }
                )
            )
        step_agent = create_agent(
            model,
            tools=tools,
            system_prompt=preamble + "\n" + spec.instructions,
            middleware=middleware,
            name=f"{spec.name}.{step.key}",
        )

        def node(state: WorkflowState, config) -> dict[str, Any]:
            outputs = dict(state.get("outputs") or {})
            if _skip(step, outputs):
                outputs[step.key] = "(skipped)"
                return {"outputs": outputs}
            ctx = {"question": state.get("question", ""), **spec.parameters, **outputs}
            prompt = f"[step: {step.key}] [request: {state.get('question', '')}]\n" + render(
                step.prompt, ctx
            )
            result = step_agent.invoke({"messages": [HumanMessage(content=prompt)]}, config)
            msgs = result["messages"][1:]  # drop the rendered prompt; keep tool and AI messages
            final = next(
                (
                    _text(m.content)
                    for m in reversed(msgs)
                    if isinstance(m, AIMessage) and _text(m.content).strip()
                ),
                "",
            )
            outputs[step.key] = final
            return {"outputs": outputs, "messages": msgs}

        return node

    prev = "start"
    for step in spec.steps:
        graph.add_node(step.key, make_node(step))
        graph.add_edge(prev, step.key)
        prev = step.key
    graph.add_edge(START, "start")
    graph.add_edge(prev, END)
    return graph.compile(checkpointer=checkpointer, name=spec.name)
