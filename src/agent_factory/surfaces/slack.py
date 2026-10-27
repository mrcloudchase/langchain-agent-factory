"""Slack surface: a Bolt app that forwards mentions to a factory agent on the Agent Server.

Run: `python -m agent_factory.surfaces.slack research_digest` with SLACK_BOT_TOKEN and
SLACK_APP_TOKEN (Socket Mode). Each agent gets its own Slack app identity, which is the
same model LangSmith Fleet uses for no-code agents. Approvals are not resolved in Slack;
they surface in the LangSmith Agent Inbox, and the bot says so.
"""

from __future__ import annotations

import os
import re
import sys

from agent_factory.spec import load_spec
from agent_factory.surfaces import deployment_url


def ask_agent(assistant_id: str, text: str, thread_key: str, *, client=None) -> str:
    """Run one turn on the Agent Server, keyed by Slack thread, and return the reply."""
    if client is None:
        from langgraph_sdk import get_sync_client

        client = get_sync_client(url=deployment_url())
    thread = client.threads.create(thread_id=thread_key, if_exists="do_nothing")
    result = client.runs.wait(
        thread["thread_id"],
        assistant_id,
        input={"messages": [{"role": "user", "content": text}]},
        metadata={"surface": "slack"},
    )
    if result.get("__interrupt__"):
        names = [a["name"] for a in result["__interrupt__"][0]["value"]["action_requests"]]
        return f"Waiting for approval in the LangSmith Agent Inbox: {', '.join(names)}."
    msgs = result.get("messages", [])
    return msgs[-1]["content"] if msgs else "(no reply)"


def main(agent_name: str) -> None:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    spec = load_spec(agent_name)
    bolt = App(token=os.environ["SLACK_BOT_TOKEN"])

    @bolt.event("app_mention")
    def on_mention(event, say):
        text = re.sub(r"<@[A-Z0-9]+>", "", event["text"]).strip()
        key = f"slack-{event.get('thread_ts') or event['ts']}"
        say(text=ask_agent(spec.name, text, key), thread_ts=event.get("thread_ts") or event["ts"])

    SocketModeHandler(bolt, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main(sys.argv[1])
