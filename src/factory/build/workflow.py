"""Workflow archetype: fixed steps compiled to a LangGraph graph.

Each step is one bounded `create_agent` call limited to that step's tools, with the org
middleware and human approval on sensitive tools. Step outputs feed later step prompts.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from factory.build.agent import system_prompt
from factory.build.middleware import org_middleware
from factory.build.models import STEP_MARKER, text_of
from factory.build.tools import load_tools
from factory.spec import Spec, Step, render


class WorkflowState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    question: str
    outputs: dict[str, str]


def _first_question(state: WorkflowState) -> dict[str, Any]:
    human = next(m for m in state["messages"] if isinstance(m, HumanMessage))
    return {"question": text_of(human.content), "outputs": {}}


def _step_node(spec: Spec, step: Step, model: BaseChatModel):
    middleware = org_middleware(f"{spec.name}.{step.key}", spec.team, step.tools, spec.limits)
    gated = [t for t in step.tools if t in spec.approvals]
    if gated:
        middleware.append(HumanInTheLoopMiddleware(dict.fromkeys(gated, True)))
    runner = create_agent(
        model,
        tools=load_tools(step.tools),
        system_prompt=system_prompt(spec),
        middleware=middleware,
        name=f"{spec.name}.{step.key}",
    )

    def node(state: WorkflowState, config) -> dict[str, Any]:
        question = state["question"]
        prompt = STEP_MARKER.format(step=step.key, question=question) + render(
            step.prompt, {"question": question, **state["outputs"]}
        )
        produced = runner.invoke({"messages": [HumanMessage(content=prompt)]}, config)["messages"][
            1:
        ]
        answer = next(
            (
                text_of(m.content)
                for m in reversed(produced)
                if isinstance(m, AIMessage) and text_of(m.content).strip()
            ),
            "",
        )
        return {"outputs": {**state["outputs"], step.key: answer}, "messages": produced}

    return node


def build_workflow(spec: Spec, model: BaseChatModel, checkpointer: Any = None):
    assert spec.steps, "a workflow needs steps"
    graph = StateGraph(WorkflowState)
    graph.add_node("start", _first_question)
    graph.add_edge(START, "start")
    previous = "start"
    for step in spec.steps:
        graph.add_node(step.key, _step_node(spec, step, model))
        graph.add_edge(previous, step.key)
        previous = step.key
    graph.add_edge(previous, END)
    return graph.compile(checkpointer=checkpointer, name=spec.name)
