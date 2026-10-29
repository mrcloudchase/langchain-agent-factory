"""Webhook surface: external systems start runs with a shared secret.

The secret is verified before anything else happens, so an unauthenticated request can never
start a run.
"""

from __future__ import annotations

import asyncio
import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from factory import config
from factory.server.deps import sdk
from factory.server.runs import start_run
from factory.spec import load_spec

router = APIRouter()


def verify_secret(provided: str | None) -> None:
    expected = config.webhook_secret()
    if not (expected and provided and hmac.compare_digest(provided, expected)):
        raise HTTPException(401, "bad or missing X-Factory-Secret")


@router.post("/webhooks/{agent}")
async def receive(
    agent: str, request: Request, x_factory_secret: str | None = Header(default=None)
) -> dict:
    verify_secret(x_factory_secret)
    spec = await asyncio.to_thread(load_spec, agent)
    if "webhook" not in spec.surfaces:
        raise HTTPException(404, f"{agent} does not accept webhooks")
    question = (await request.json()).get("question", "").strip()
    if not question:
        raise HTTPException(422, "body needs a 'question'")
    return await start_run(sdk(request), agent, question, surface="webhook")
