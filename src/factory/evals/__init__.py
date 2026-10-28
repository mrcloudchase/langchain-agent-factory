"""Evaluation gate: no agent is promoted without passing its evals. Offline and online use the
same evaluators; online syncs datasets to LangSmith and uploads experiments."""

from factory.evals.gate import GateReport, run_gate

__all__ = ["GateReport", "run_gate"]
