"""Model resolution, including a deterministic offline mode.

Online: the spec's model tier resolves to a registered provider model via
`init_chat_model`. Offline (no provider key, or FACTORY_OFFLINE=1): a scripted model
replays the trajectories recorded next to each eval example, so policy checks, the
harness, human-in-the-loop, and the eval gate all run in CI without secrets.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent_factory.registry import load_registry

PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}


def provider_of(model_id: str) -> str:
    return model_id.split(":", 1)[0] if ":" in model_id else "anthropic"


def is_offline(model_id: str | None = None) -> bool:
    """Offline when forced, or when the provider for the requested model has no key."""
    if os.environ.get("FACTORY_OFFLINE", "0") in ("1", "true", "yes"):
        return True
    if model_id is None:
        return not any(os.environ.get(k) for k in PROVIDER_KEYS.values())
    key = PROVIDER_KEYS.get(provider_of(model_id))
    return not (key and os.environ.get(key))


class Step(dict):
    """One scripted step: {"tool": name, "args": {...}} or {"answer": "..."}."""


class ScriptedChatModel(BaseChatModel):
    """Replays recorded trajectories keyed by the user's request.

    Each trajectory is a list of steps. Progress is derived from the number of AI
    messages already in the conversation, so the model is stateless and resumes
    correctly after a human-in-the-loop interrupt.
    """

    scripts: dict[str, list[dict[str, Any]]]
    default_answer: str = "I do not have a scripted response for that request (offline mode)."
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

    def _pick_script(self, messages: list[BaseMessage]) -> list[dict[str, Any]] | None:
        first_human = next((m for m in messages if isinstance(m, HumanMessage)), None)
        if first_human is None:
            return None
        text = _text(first_human.content).lower()
        # Exact match first, then longest key contained in the request.
        if text in self.scripts:
            return self.scripts[text]
        best = None
        for key, script in self.scripts.items():
            if key in text and (best is None or len(key) > len(best[0])):
                best = (key, script)
        return best[1] if best else None

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        script = self._pick_script(messages)
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
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        msg = result.generations[0].message
        yield ChatGenerationChunk(
            message=AIMessageChunk(content=msg.content, tool_calls=msg.tool_calls, id=msg.id)
        )


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content)


def scripts_from_dataset(dataset_path) -> dict[str, list[dict[str, Any]]]:
    """Build the offline script table from the eval dataset's `offline_trajectory` fields."""
    scripts: dict[str, list[dict[str, Any]]] = {}
    if not dataset_path.exists():
        return scripts
    for line in dataset_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        traj = row.get("offline_trajectory")
        question = (row.get("inputs") or {}).get("question")
        if traj and question:
            scripts[question.strip().lower()] = traj
    return scripts


def resolve_model(
    model_tier: str, *, dataset_path=None, offline: bool | None = None
) -> BaseChatModel:
    """Turn a registry tier into a chat model, or a scripted model when offline."""
    reg = load_registry()
    tier = reg.model_tier(model_tier)
    if tier is None:
        raise ValueError(f"unknown model tier: {model_tier}")
    off = is_offline(tier.model) if offline is None else offline
    if off:
        scripts = scripts_from_dataset(dataset_path) if dataset_path else {}
        return ScriptedChatModel(scripts=scripts)
    from langchain.chat_models import init_chat_model

    return init_chat_model(tier.model)
