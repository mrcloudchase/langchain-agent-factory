"""The ledger: stages, promotion requests, and decisions, as a JSON file under .factory/."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from factory.paths import STATE_DIR

LEDGER = STATE_DIR / "ledger.json"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def load() -> dict[str, Any]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"agents": {}, "promotions": []}


def save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=2))


def current_stage(name: str) -> str:
    return load()["agents"].get(name, {}).get("stage", "dev")


def set_stage(name: str, stage: str, **extra: Any) -> None:
    data = load()
    entry = data["agents"].setdefault(name, {"history": []})
    entry["stage"] = stage
    entry["history"].append({"stage": stage, "at": _now(), **extra})
    save(data)


def forget(name: str) -> None:
    data = load()
    data["agents"].pop(name, None)
    data["promotions"] = [p for p in data["promotions"] if p["agent"] != name]
    save(data)


def add_promotion(
    agent: str, to: str, requested_by: str | None, gates: dict[str, Any], needs: list[str]
) -> dict[str, Any]:
    data = load()
    req = {
        "id": uuid.uuid4().hex[:10],
        "agent": agent,
        "to": to,
        "requested_by": requested_by,
        "requested_at": _now(),
        "gates": gates,
        "needs": needs,
        "approvals": [],
        "status": "pending",
    }
    data["promotions"].append(req)
    save(data)
    return req


def get_promotion(pid: str) -> dict[str, Any] | None:
    return next((p for p in load()["promotions"] if p["id"] == pid), None)


def update_promotion(pid: str, **fields: Any) -> dict[str, Any]:
    data = load()
    for p in data["promotions"]:
        if p["id"] == pid:
            p.update(fields)
            save(data)
            return p
    raise KeyError(pid)


def pending_promotions(agent: str | None = None) -> list[dict[str, Any]]:
    return [
        p
        for p in load()["promotions"]
        if p["status"] == "pending" and (agent is None or p["agent"] == agent)
    ]


def history(agent: str) -> list[dict[str, Any]]:
    return load()["agents"].get(agent, {}).get("history", [])
