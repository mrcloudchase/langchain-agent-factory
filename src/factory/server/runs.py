"""Start and inspect runs on the Agent Server through the async SDK.

Every agent is an assistant on the `factory` graph. Threads carry the agent's name in their
metadata, which is how the console finds activity and approvals per agent.
"""

from __future__ import annotations

from typing import Any

from factory.build.models import text_of


async def assistant_id(client, agent: str) -> str:
    found = await client.assistants.search(graph_id="factory", metadata={"agent": agent}, limit=1)
    if found:
        return found[0]["assistant_id"]
    created = await client.assistants.create(
        graph_id="factory",
        config={"configurable": {"agent": agent}},
        metadata={"agent": agent},
        name=agent,
    )
    return created["assistant_id"]


async def start_run(
    client, agent: str, question: str, surface: str, user: str | None = None
) -> dict[str, Any]:
    assistant = await assistant_id(client, agent)
    thread = await client.threads.create(
        metadata={"agent": agent, "surface": surface, "user": user}
    )
    run = await client.runs.create(
        thread["thread_id"],
        assistant,
        input={"messages": [{"role": "user", "content": question}]},
        metadata={"agent": agent, "surface": surface, "user": user},
    )
    return {"thread_id": thread["thread_id"], "run_id": run["run_id"], "assistant_id": assistant}


async def resume(
    client, thread_id: str, agent: str, decisions: list[dict], user: str
) -> dict[str, Any]:
    run = await client.runs.create(
        thread_id,
        await assistant_id(client, agent),
        command={"resume": {"decisions": decisions}},
        metadata={"agent": agent, "surface": "console", "user": user},
    )
    return {"thread_id": thread_id, "run_id": run["run_id"]}


def interrupts(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Pending approval requests in a thread state: [{name, args, allowed}]."""
    found = []
    for task in state.get("tasks") or []:
        for item in task.get("interrupts") or []:
            value = item.get("value") or {}
            allowed = {
                c["action_name"]: c["allowed_decisions"] for c in value.get("review_configs", [])
            }
            found += [
                {
                    "name": r["name"],
                    "args": r.get("args", {}),
                    "allowed": allowed.get(r["name"], ["approve", "reject"]),
                }
                for r in value.get("action_requests", [])
            ]
    return found


def messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": m.get("type"),
            "name": m.get("name"),
            "content": text_of(m.get("content")),
            "tool_calls": [tc.get("name") for tc in m.get("tool_calls") or []],
        }
        for m in (state.get("values") or {}).get("messages") or []
    ]


def summary(thread: dict[str, Any]) -> dict[str, Any]:
    meta = thread.get("metadata") or {}
    msgs = messages({"values": thread.get("values") or {}})
    asked = next((m["content"] for m in msgs if m["type"] == "human"), "")
    answer = next(
        (m["content"] for m in reversed(msgs) if m["type"] == "ai" and m["content"].strip()), ""
    )
    return {
        "thread_id": thread["thread_id"],
        "agent": meta.get("agent"),
        "surface": meta.get("surface"),
        "user": meta.get("user"),
        "status": thread.get("status"),
        "question": asked.split("\n")[-1][:200],
        "answer": answer[:300],
        "tools": [m["name"] for m in msgs if m["type"] == "tool"],
        "updated_at": thread.get("updated_at"),
    }
