"""Knowledge base search over data/kb/*.md, by section."""

from __future__ import annotations

import re

from langchain_core.tools import tool

from factory.tools.data import kb_files


@tool
def knowledge_search(query: str, max_results: int = 3) -> str:
    """Search the company knowledge base (policies, runbooks, standards). Returns matching
    sections with their source file so you can cite them."""
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    hits = []
    for path in kb_files():
        for section in re.split(r"\n(?=## )", path.read_text()):
            score = sum(section.lower().count(t) for t in terms)
            if score:
                hits.append((score, path.name, section.strip()))
    hits.sort(key=lambda h: -h[0])
    if not hits:
        return "No knowledge base articles matched."
    return "\n\n---\n\n".join(f"[{name}]\n{body[:900]}" for _, name, body in hits[:max_results])
