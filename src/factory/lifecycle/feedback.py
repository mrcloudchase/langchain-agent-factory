"""Turn a bad production answer into an eval case.

Anyone who sees a bad answer flags it; the flag is recorded as LangSmith feedback on the run
when tracing is on, and as a pending case for the agent. The builder writes what a correct
answer must contain and accepts it, and from then on the gate runs it on every promotion.
"""

from __future__ import annotations

import uuid
from typing import Any

from factory import config
from factory.agents import now, store
from factory.org import User


def flag(
    agent: str, by: User, question: str, answer: str, note: str = "", run_id: str | None = None
) -> dict[str, Any]:
    assert question.strip(), "a flagged case needs the question that was asked"
    case = {
        "id": f"{agent}-flag-{uuid.uuid4().hex[:6]}",
        "inputs": {"question": question},
        "observed": answer,
        "note": note,
        "flagged_by": by.id,
        "at": now(),
        "run_id": run_id,
        "langsmith_feedback": _record_feedback(run_id, by, note),
    }
    s = store()
    s.write_pending(agent, [*s.pending(agent), case])
    return case


def _record_feedback(run_id: str | None, by: User, note: str) -> bool:
    if not (run_id and config.langsmith()):
        return False
    from langsmith import Client

    Client().create_feedback(
        run_id=run_id, key="flagged", score=0, comment=f"{by.name}: {note}".strip(": ")
    )
    return True


def accept(agent: str, case_id: str, must_contain: list[str], by: User) -> dict[str, Any]:
    if not must_contain:
        raise ValueError("write at least one phrase a correct answer must contain")
    if not by.can_build_for(store().load(agent).team):
        raise PermissionError(f"{by.name} cannot curate cases for {agent}")
    s = store()
    pending = s.pending(agent)
    case = next((c for c in pending if c["id"] == case_id), None)
    if case is None:
        raise KeyError(f"no pending case '{case_id}'")
    accepted = {
        "id": case["id"],
        "inputs": case["inputs"],
        "outputs": {"must_contain": must_contain},
        "metadata": {"split": "flagged", "observed": case["observed"], "accepted_by": by.id},
    }
    s.write_dataset(agent, [*s.dataset(agent), accepted])
    s.write_pending(agent, [c for c in pending if c["id"] != case_id])
    return accepted
