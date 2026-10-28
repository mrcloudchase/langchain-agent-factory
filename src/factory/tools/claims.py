"""Claims tools: a recording action that stands in for a claims system of record."""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def record_claim_decision(policy_number: str, decision: str, amount_usd: float, reason: str) -> str:
    """Record a claim decision (approve, deny, or refer) with the amount and the policy reason.
    This is the system of record; it always pauses for a human to confirm."""
    decision = decision.lower().strip()
    if decision not in ("approve", "deny", "refer"):
        return f"Refused: decision must be approve, deny, or refer (got '{decision}')."
    return (
        f"Recorded: policy {policy_number} -> {decision} for ${amount_usd:,.2f}. "
        f"Reason: {reason} Reference CL-{policy_number[-4:]}."
    )
