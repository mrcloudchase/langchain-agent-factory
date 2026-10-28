"""Roles for the demo: the console sends X-Factory-User; the registry says what that user may do.

In production this is the Agent Server's auth block (SSO) feeding the same checks.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from factory.core.registry import User, load_registry


def current_user(x_factory_user: str | None = Header(default=None)) -> User | None:
    return load_registry().user(x_factory_user)


def require(user: User | None, *roles: str) -> User:
    if user is None:
        raise HTTPException(401, "sign in as a user (X-Factory-User)")
    if roles and user.role not in roles:
        raise HTTPException(403, f"role '{user.role}' may not do this; needs one of {roles}")
    return user


def can_build_for(user: User | None, team: str) -> bool:
    return user is not None and (
        user.role == "platform" or (user.role in ("builder", "approver") and user.team == team)
    )
