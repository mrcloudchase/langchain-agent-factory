"""Agent Factory: a shared foundation for building, governing, and shipping agents across an org.

Built on LangChain, LangGraph, Deep Agents, and LangSmith. This is an independent
demonstration project, not an official LangChain product.
"""

from agent_factory.harness import build_agent
from agent_factory.spec import AgentSpec, load_spec

__all__ = ["AgentSpec", "build_agent", "load_spec"]
__version__ = "0.1.0"
