"""The custom FastAPI app the Agent Server mounts: webhook surface + console."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse

from factory.console.api.routes import router
from factory.surfaces.webhook import app

PAGE = (Path(__file__).parent / "ui" / "index.html").read_text()

app.include_router(router)


@app.get("/console", response_class=HTMLResponse)
@app.get("/console/", response_class=HTMLResponse)
async def console_page() -> str:
    return PAGE
