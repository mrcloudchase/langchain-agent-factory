"""Messaging tools. Sending is simulated; the registry decides who may use it."""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def send_slack_message(channel: str, text: str) -> str:
    """Post a message to a Slack channel as the agent's bot identity."""
    return f"Posted to #{channel.lstrip('#')} ({len(text)} chars)."
