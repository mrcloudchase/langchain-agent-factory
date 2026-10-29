"""Live research sources: Hugging Face Papers (arXiv papers), Hacker News, PyPI releases."""

from __future__ import annotations

import datetime as dt
import json
import xml.etree.ElementTree as ET

from langchain_core.tools import tool

from factory.tools.http import get_text


@tool
def paper_search(query: str, limit: int = 5) -> str:
    """Search recent AI research papers. Returns title, date, arXiv URL, and a short abstract."""
    hits = json.loads(
        get_text("https://huggingface.co/api/papers/search", {"q": query, "limit": limit})
    )
    if not hits:
        return "No papers found."
    lines = []
    for hit in hits[:limit]:
        paper = hit["paper"]
        summary = _clean(paper.get("summary"))[:240]
        date = (hit.get("publishedAt") or paper.get("publishedAt") or "")[:10]
        title = _clean(hit.get("title") or paper["title"])
        lines.append(f"- {title} ({date}) https://arxiv.org/abs/{paper['id']} :: {summary}")
    return "\n".join(lines)


def _when(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


@tool
def hn_search(query: str, days: int = 30) -> str:
    """Search recent Hacker News stories. Returns title, date, points, and URL."""
    hits = json.loads(
        get_text(
            "https://hn.algolia.com/api/v1/search_by_date",
            {"query": query, "tags": "story", "hitsPerPage": 10},
        )
    )["hits"]
    if not hits:
        return "No stories found."
    # The window is measured from the newest story, so recorded responses replay unchanged.
    newest = _when(hits[0]["created_at"])
    recent = [h for h in hits if newest - _when(h["created_at"]) <= dt.timedelta(days=days)]
    return "\n".join(
        f"- {_clean(h['title'])} ({h['created_at'][:10]}, {h.get('points') or 0} points) "
        f"{h.get('url') or 'https://news.ycombinator.com/item?id=' + h['objectID']}"
        for h in recent
    )


@tool
def package_releases(package: str, limit: int = 3) -> str:
    """Read the most recent releases of a Python package from PyPI."""
    items = ET.fromstring(get_text(f"https://pypi.org/rss/project/{package}/releases.xml")).findall(
        "./channel/item"
    )
    if not items:
        return f"No releases found for {package}."
    return "\n".join(
        f"- {package} {i.findtext('title')} ({i.findtext('pubDate')}) {i.findtext('link')}"
        for i in items[:limit]
    )
