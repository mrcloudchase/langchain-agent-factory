"""Agent Factory v2: the operating-model layer for running many agents on LangChain.

The organization defines archetypes, templates, a tool catalog, and processes under org/.
Teams create instances (a template plus parameters). The factory generates the spec,
enforces policy, builds the agent, gates promotion, opens surfaces, and keeps the catalog.
Independent demonstration; not an official LangChain product.
"""

__version__ = "2.0.0"
