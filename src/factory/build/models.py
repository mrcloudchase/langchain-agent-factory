"""Model resolution: the tier's model when live, a scripted model when offline.

Offline, the scripted model replays the trajectories recorded next to each eval example.
Agent examples hold a list of steps keyed by the request. Workflow examples hold one list per
workflow step; each step prompt starts with a marker line naming the step and the request.
Progress is the number of AI messages already present, so replay resumes correctly after a
human approval.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from factory import config
from factory.spec import Spec

STEP_MARKER = "[step: {step}] [request: {question}]\n"
_MARKER = re.compile(r"\[step: ([a-z0-9_]+)\] \[request: (.*?)\]\n", re.S)


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return "" if content is None else str(content)


class ScriptedModel(BaseChatModel):
    scripts: dict[str, Any]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _script_for(self, messages: list[BaseMessage]) -> list[dict[str, Any]] | None:
        first = next((m for m in messages if isinstance(m, HumanMessage)), None)
        if first is None:
            return None
        text = text_of(first.content)
        marker = _MARKER.match(text)
        request = (marker.group(2) if marker else text).strip().lower()
        script = self.scripts.get(request)
        if script is None:
            matches = [k for k in self.scripts if k in request]
            script = self.scripts[max(matches, key=len)] if matches else None
        if marker:
            return (
                script.get("steps", {}).get(marker.group(1)) if isinstance(script, dict) else None
            )
        return script if isinstance(script, list) else None

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        script = self._script_for(messages)
        turn = sum(isinstance(m, AIMessage) for m in messages)
        if script is None:
            message = AIMessage(content="No recorded response for this request (offline mode).")
        elif turn >= len(script):
            message = AIMessage(content="Done.")
        elif "tool" in script[turn]:
            step = script[turn]
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": step["tool"],
                        "args": step.get("args", {}),
                        "id": f"call_{turn}",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            message = AIMessage(content=script[turn]["answer"])
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        message = self._generate(messages).generations[0].message
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content, tool_calls=message.tool_calls, id=message.id
            )
        )


def scripts_from(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        r["inputs"]["question"].strip().lower(): r["offline_trajectory"]
        for r in rows
        if r.get("offline_trajectory")
    }


def model_for(spec: Spec, rows: list[dict[str, Any]]) -> BaseChatModel:
    if config.offline():
        return ScriptedModel(scripts=scripts_from(rows))
    from langchain.chat_models import init_chat_model

    return init_chat_model(spec.model, **spec.model_params)
