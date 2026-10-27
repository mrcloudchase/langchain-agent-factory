"""Knowledge tools shared by every team: internal KB search and a simulated web index."""

from __future__ import annotations

import re

from langchain_core.tools import tool

from agent_factory.tools._data import kb_files, load_json


def _score(text: str, terms: list[str]) -> int:
    lower = text.lower()
    return sum(lower.count(t) for t in terms)


@tool
def knowledge_search(query: str, max_results: int = 3) -> str:
    """Search the company knowledge base (policies, runbooks, product notes). Returns the
    best-matching sections with their source file so you can cite them."""
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    hits = []
    for path in kb_files():
        for section in re.split(r"\n(?=## )", path.read_text()):
            s = _score(section, terms)
            if s:
                hits.append((s, path.name, section.strip()))
    hits.sort(key=lambda h: -h[0])
    if not hits:
        return "No knowledge base articles matched."
    return "\n\n---\n\n".join(f"[{name}]\n{body[:900]}" for _, name, body in hits[:max_results])


@tool
def web_search(query: str) -> str:
    """Search the web for recent public information. Returns titles, URLs, and snippets."""
    index = load_json("web_index.json").get("results", [])
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    scored = sorted(
        ((_score(r["title"] + " " + r["snippet"], terms), r) for r in index), key=lambda x: -x[0]
    )
    top = [r for s, r in scored if s][:4]
    if not top:
        return "No results."
    return "\n".join(f"- {r['title']} ({r['url']}): {r['snippet']}" for r in top)
