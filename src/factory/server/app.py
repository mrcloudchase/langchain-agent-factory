"""The FastAPI app the Agent Server mounts (langgraph.json http.app): console and webhook."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from factory.lifecycle.create import Refused
from factory.lifecycle.promotion import Blocked
from factory.server import api, webhook

app = FastAPI(title="Agent Factory")
app.include_router(api.router)
app.include_router(webhook.router)
_PAGE = (Path(__file__).parent / "ui" / "index.html").read_text()


@app.get("/console", response_class=HTMLResponse)
async def console() -> str:
    return _PAGE


@app.exception_handler(Refused)
async def _refused(_: Request, e: Refused) -> JSONResponse:
    return JSONResponse(
        {"detail": str(e), "violations": [v.__dict__ for v in e.violations]}, status_code=422
    )


@app.exception_handler(Blocked)
async def _blocked(_: Request, e: Blocked) -> JSONResponse:
    return JSONResponse(
        {"detail": str(e), "report": e.report.to_dict() if e.report else None}, status_code=409
    )


@app.exception_handler(PermissionError)
async def _forbidden(_: Request, e: PermissionError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(KeyError)
@app.exception_handler(FileNotFoundError)
async def _missing(_: Request, e: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(e).strip("'")}, status_code=404)


@app.exception_handler(ValueError)
async def _invalid(_: Request, e: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=422)
