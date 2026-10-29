"""HTTP GET with record and replay, so live tools also run offline and in CI.

Live: fetch. Recording (FACTORY_RECORD=1): fetch and save the response as a fixture.
Offline: replay the fixture; a missing fixture is an error, never a silent live call.
"""

from __future__ import annotations

import hashlib
import json

import httpx

from factory import config

USER_AGENT = "agent-factory/3.0 (+https://github.com/mrcloudchase/langchain-agent-factory)"


class FixtureMissing(RuntimeError):
    pass


def _fixture(url: str, params: dict) -> tuple[str, dict]:
    key = json.dumps({"url": url, "params": params}, sort_keys=True)
    path = (
        config.data_dir()
        / "fixtures"
        / "http"
        / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"
    )
    return path, {"url": url, "params": params}


def get_text(url: str, params: dict | None = None) -> str:
    params = params or {}
    path, request = _fixture(url, params)
    if config.offline() and not config.recording():
        if not path.exists():
            raise FixtureMissing(
                f"no recorded response for {url} {params}; record with FACTORY_RECORD=1"
            )
        return json.loads(path.read_text())["body"]
    response = httpx.get(
        url, params=params, timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    if config.recording():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**request, "body": response.text}))
    return response.text
