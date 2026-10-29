"""Build: turn a spec into a runnable graph by archetype."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from factory.agents import store
from factory.build.agent import build_agent
from factory.build.models import model_for
from factory.build.workflow import build_workflow
from factory.spec import Spec


def build(spec: Spec, *, model: BaseChatModel | None = None, checkpointer: Any = None):
    model = model or model_for(spec, store().dataset(spec.name))
    builder = build_workflow if spec.archetype == "workflow" else build_agent
    return builder(spec, model, checkpointer)
