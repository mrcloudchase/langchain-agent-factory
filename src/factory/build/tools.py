"""Load catalog tools by name. A name outside the catalog is a programming error."""

from __future__ import annotations

import importlib

from langchain_core.tools import BaseTool

from factory.org import load_org


def load_tools(names: list[str]) -> list[BaseTool]:
    catalog = load_org().tools
    tools = []
    for name in names:
        module, _, attr = catalog[name].impl.partition(":")
        tool = getattr(importlib.import_module(module), attr)
        assert isinstance(tool, BaseTool) and tool.name == name, (
            f"catalog entry '{name}' does not match {tool!r}"
        )
        tools.append(tool)
    return tools
