"""Engineering tools. Repo reads are real (they read this repository); writes are simulated."""

from __future__ import annotations

import re

from langchain_core.tools import tool

from factory import config
from factory.tools.data import load_json

_SKIP = {".git", ".venv", "__pycache__", ".factory", ".langgraph_api", "node_modules", "fixtures"}


def _safe(path: str):
    root = config.root().resolve()
    p = (root / path).resolve()
    if root not in p.parents:
        raise ValueError("path escapes repository")
    return p


@tool
def read_repo_file(path: str, max_lines: int = 200) -> str:
    """Read a file from the repository by relative path."""
    p = _safe(path)
    if not p.exists() or not p.is_file():
        return f"{path}: not found"
    lines = p.read_text(errors="replace").splitlines()[:max_lines]
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))


@tool
def search_code(pattern: str, glob: str = "*.py", max_hits: int = 20) -> str:
    """Search repository files matching a glob for a regex pattern. Returns path:line hits."""
    rx = re.compile(pattern)
    hits = []
    root = config.root()
    for p in root.rglob(glob):
        if any(part in _SKIP for part in p.parts):
            continue
        try:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(root)}:{i}: {line.strip()[:120]}")
                    if len(hits) >= max_hits:
                        return "\n".join(hits)
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(hits) if hits else "No matches."


@tool
def read_ci_status(pr_number: int) -> str:
    """Read the latest CI result and failing test names for a pull request."""
    pr = load_json("ci.json").get("pull_requests", {}).get(str(pr_number))
    if not pr:
        return f"PR #{pr_number}: no CI data."
    failing = ", ".join(pr["failing_tests"]) or "none"
    return (
        f"PR #{pr_number} '{pr['title']}': ci={pr['status']} failing_tests={failing}\n{pr['log']}"
    )


@tool
def post_pr_comment(pr_number: int, body: str) -> str:
    """Post a review comment on a pull request. Visible to the whole team; requires approval."""
    return f"Comment posted on PR #{pr_number} ({len(body)} chars)."
