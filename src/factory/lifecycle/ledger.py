"""The ledger: each agent's stage history and its promotion requests, in one JSON file."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from factory import config
from factory.agents import now


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, Any]:
        return (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"stages": {}, "requests": []}
        )

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def history(self, agent: str) -> list[dict[str, Any]]:
        return self._read()["stages"].get(agent, [])

    def stage(self, agent: str, first: str) -> str:
        history = self.history(agent)
        return history[-1]["stage"] if history else first

    def advance(self, agent: str, stage: str, **evidence: Any) -> None:
        data = self._read()
        data["stages"].setdefault(agent, []).append({"stage": stage, "at": now(), **evidence})
        self._write(data)

    def open_request(
        self, agent: str, to: str, by: str, needs: list[str], evidence: dict[str, Any]
    ) -> dict[str, Any]:
        assert not self.pending(agent), f"{agent} already has an open promotion request"
        request = {
            "id": uuid.uuid4().hex[:8],
            "agent": agent,
            "to": to,
            "requested_by": by,
            "requested_at": now(),
            "needs": needs,
            "approvals": [],
            "evidence": evidence,
            "status": "pending",
        }
        data = self._read()
        data["requests"].append(request)
        self._write(data)
        return request

    def request(self, request_id: str) -> dict[str, Any]:
        found = [r for r in self._read()["requests"] if r["id"] == request_id]
        if not found:
            raise KeyError(f"no promotion request '{request_id}'")
        return found[0]

    def update_request(self, request_id: str, **changes: Any) -> dict[str, Any]:
        data = self._read()
        request = next(r for r in data["requests"] if r["id"] == request_id)
        request.update(changes)
        self._write(data)
        return request

    def pending(self, agent: str | None = None) -> list[dict[str, Any]]:
        return [
            r
            for r in self._read()["requests"]
            if r["status"] == "pending" and agent in (None, r["agent"])
        ]

    def forget(self, agent: str) -> None:
        data = self._read()
        data["stages"].pop(agent, None)
        data["requests"] = [r for r in data["requests"] if r["agent"] != agent]
        self._write(data)


def ledger() -> Ledger:
    return Ledger(config.state_dir() / "ledger.json")
