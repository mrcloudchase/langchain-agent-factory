"""Request-scoped dependencies: the Agent Server client and the signed-in user."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from factory.org import User, load_org


def sdk(request: Request):
    """The app's own Agent Server, reached through the async SDK (tests inject a fake)."""
    injected = getattr(request.app.state, "sdk", None)
    if injected is not None:
        return injected
    from langgraph_sdk import get_client

    return get_client(url=str(request.base_url).rstrip("/"))


def optional_user(x_factory_user: str | None = Header(default=None)) -> User | None:
    """Demo identity: a header resolved against org/teams.yaml. Production uses the Agent
    Server's auth handler (SSO) to produce the same User."""
    return load_org().user(x_factory_user)


def user(x_factory_user: str | None = Header(default=None)) -> User:
    found = optional_user(x_factory_user)
    if found is None:
        raise HTTPException(401, "sign in (X-Factory-User)")
    return found
