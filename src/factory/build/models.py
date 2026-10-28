"""Model resolution and the offline scripted model.

Offline, a scripted model replays trajectories recorded next to each example. Agent scripts
are a flat list keyed by the request. Workflow scripts are keyed by the request and then by
step; each step prompt starts with a marker line `[step: <key>] [request: <question>]` so the
model can find the right script without any state.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from factory.core.registry import load_registry

PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}
MARKER = re.compile(r"\[step: ([a-z0-9_]+)\] \[request: (.*?)\]\n", re.S)


def provider_of(model_id: str) -> str:
    return model_id.split(":", 1)[0] if ":" in model_id else "anthropic"


def is_offline(model_id: str | None = None) -> bool:
    if os.environ.get("FACTORY_OFFLINE", "0") in ("1", "true", "yes"):
        return True
    if model_id is None:
        return not any(os.environ.get(k) for k in PROVIDER_KEYS.values())
    key = PROVIDER_KEYS.get(provider_of(model_id))
    return not (key and os.environ.get(key))


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content)


class ScriptedChatModel(BaseChatModel):
    scripts: dict[str, Any]
    default_answer: str = "No scripted response for that request (offline mode)."
    tools_bound: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        names = []
        for t in tools:
            names.append(
                getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else str(t))
            )
        return self.model_copy(update={"tools_bound": names})

    def _lookup(self, text: str) -> Any:
        text = text.lower().strip()
        if text in self.scripts:
            return self.scripts[text]
        best = None
        for key, script in self.scripts.items():
            if key in text and (best is None or len(key) > len(best[0])):
                best = (key, script)
        return best[1] if best else None

    def _pick(self, messages: list[BaseMessage]) -> list[dict[str, Any]] | None:
        first_human = next((m for m in messages if isinstance(m, HumanMessage)), None)
        if first_human is None:
            return None
        text = _text(first_human.content)
        m = MARKER.match(text)
        if m:
            step, request = m.group(1), m.group(2)
            script = self._lookup(request)
            if isinstance(script, dict):
                return (script.get("steps") or {}).get(step)
            return None
        script = self._lookup(text)
        return script if isinstance(script, list) else None

    def _generate(
        self, messages, stop=None, run_manager: CallbackManagerForLLMRun | None = None, **kw
    ) -> ChatResult:
        script = self._pick(messages)
        n_ai = sum(1 for m in messages if isinstance(m, AIMessage))
        if script is None or n_ai >= len(script):
            msg = AIMessage(content=self.default_answer if script is None else "Done.")
        else:
            step = script[n_ai]
            if "tool" in step:
                msg = AIMessage(
                    content=step.get("thought", ""),
                    tool_calls=[
                        {
                            "name": step["tool"],
                            "args": step.get("args", {}),
                            "id": f"call_{n_ai}",
                            "type": "tool_call",
                        }
                    ],
                )
            else:
                msg = AIMessage(content=step.get("answer", ""))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator:
        msg = (
            self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            .generations[0]
            .message
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(content=msg.content, tool_calls=msg.tool_calls, id=msg.id)
        )


def scripts_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scripts: dict[str, Any] = {}
    for row in rows:
        traj = row.get("offline_trajectory")
        q = (row.get("inputs") or {}).get("question")
        if traj and q:
            scripts[q.strip().lower()] = traj
    return scripts


def resolve_model(
    model_tier: str, *, rows: list[dict[str, Any]] | None = None, offline: bool | None = None
) -> BaseChatModel:
    reg = load_registry()
    tier = reg.model_tier(model_tier)
    if tier is None:
        raise ValueError(f"unknown model tier: {model_tier}")
    off = is_offline(tier.model) if offline is None else offline
    if off:
        return ScriptedChatModel(scripts=scripts_from_rows(rows or []))
    from langchain.chat_models import init_chat_model

    return init_chat_model(tier.model, **tier.params)
