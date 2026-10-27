"""Evaluation gate: no agent is promoted without passing its evals.

Offline (no LangSmith key) the same evaluators run locally over the same dataset so CI
never needs secrets. Online, datasets are synced to LangSmith and experiments are
uploaded so results are inspectable in the UI and comparable across runs.
"""

from agent_factory.evals.gate import GateReport, run_gate

__all__ = ["GateReport", "run_gate"]
