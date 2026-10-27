"""The catalog: one page that answers "what agents do we have, who owns them, where do they
run, are they any good". Generated from specs, policy, the ledger, and the latest gate reports."""

from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Any

from agent_factory.paths import CATALOG_DIR, STATE_DIR
from agent_factory.policy import check_spec
from agent_factory.promote import current_stage, load_ledger
from agent_factory.registry import load_registry
from agent_factory.spec import list_specs


def latest_report(name: str) -> dict[str, Any] | None:
    p = STATE_DIR / "reports" / f"{name}-latest.json"
    return json.loads(p.read_text()) if p.exists() else None


def build_catalog() -> dict[str, Any]:
    reg = load_registry()
    ledger = load_ledger()
    agents = []
    for spec in list_specs():
        policy = check_spec(spec, reg)
        report = latest_report(spec.name)
        tier = reg.model_tier(spec.model_tier)
        agents.append(
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "team": spec.team,
                "owner": spec.owner,
                "purpose": spec.purpose,
                "model_tier": spec.model_tier,
                "model": tier.model if tier else None,
                "tools": [
                    {
                        "name": t,
                        "sensitive": bool(reg.tool(t) and reg.tool(t).sensitive),
                        "approval": t in spec.oversight.approve,
                    }
                    for t in spec.tools
                ],
                "subagents": [s.name for s in spec.subagents],
                "surfaces": [s.model_dump(exclude_none=True) for s in spec.surfaces],
                "limits": spec.limits.model_dump(),
                "stage": current_stage(spec.name),
                "stages": ledger.get(spec.name, {}),
                "policy_ok": policy.ok,
                "policy_warnings": [v.message for v in policy.warnings],
                "policy_errors": [v.message for v in policy.errors],
                "eval": (
                    {
                        "passed": report["passed"],
                        "mode": report["mode"],
                        "timestamp": report["timestamp"],
                        "scores": {s["key"]: s["mean"] for s in report["scores"]},
                        "experiment_url": report.get("experiment_url"),
                    }
                    if report
                    else None
                ),
                "tags": spec.tags,
            }
        )
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "teams": {k: v.model_dump() for k, v in reg.teams.items()},
        "tools": {k: v.model_dump(exclude={"impl"}) for k, v in reg.tools.items()},
        "model_tiers": {k: v.model_dump() for k, v in reg.models.items()},
        "agents": agents,
    }


def _badge(text: str, kind: str) -> str:
    return f'<span class="badge {kind}">{html.escape(text)}</span>'


def render_html(cat: dict[str, Any]) -> str:
    rows = []
    for a in cat["agents"]:
        tools = " ".join(
            _badge(
                t["name"] + (" (approval)" if t["approval"] else ""),
                "warn" if t["sensitive"] else "tool",
            )
            for t in a["tools"]
        )
        surfaces = " ".join(
            _badge(
                s["kind"]
                + (
                    f": {s.get('target') or s.get('schedule')}"
                    if s.get("target") or s.get("schedule")
                    else ""
                ),
                "surface",
            )
            for s in a["surfaces"]
        )
        ev = a["eval"]
        if ev:
            scores = ", ".join(f"{k} {v:.2f}" for k, v in ev["scores"].items())
            evcell = (
                _badge("pass" if ev["passed"] else "fail", "ok" if ev["passed"] else "bad")
                + f"<div class='small'>{html.escape(scores)}<br>{ev['mode']} · {ev['timestamp'][:16]}</div>"
            )
        else:
            evcell = _badge("not run", "muted")
        stage = a["stage"] or "unpromoted"
        policy = _badge("ok", "ok") if a["policy_ok"] else _badge("violations", "bad")
        if a["policy_warnings"]:
            policy += (
                "<div class='small'>"
                + "<br>".join(html.escape(w) for w in a["policy_warnings"])
                + "</div>"
            )
        rows.append(
            f"<tr><td><b>{html.escape(a['display_name'])}</b><div class='small'>{a['name']} · {html.escape(a['purpose'])}</div></td>"
            f"<td>{html.escape(a['team'])}<div class='small'>{html.escape(a['owner'])}</div></td>"
            f"<td>{_badge(stage, 'stage')}</td><td>{a['model_tier']}<div class='small'>{a['model'] or ''}</div></td>"
            f"<td>{tools}</td><td>{surfaces}</td><td>{policy}</td><td>{evcell}</td></tr>"
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Agent Catalog</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;color:#1a1a1a;background:#fafafa}}
h1{{margin-bottom:0}} .sub{{color:#666;margin-top:.25rem}}
table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
th,td{{text-align:left;vertical-align:top;padding:.6rem .7rem;border-bottom:1px solid #eee;font-size:14px}}
th{{background:#f3f4f6;font-weight:600}}
.badge{{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:12px;margin:.1rem;background:#e5e7eb}}
.badge.ok{{background:#d1fae5;color:#065f46}} .badge.bad{{background:#fee2e2;color:#991b1b}}
.badge.warn{{background:#fef3c7;color:#92400e}} .badge.surface{{background:#dbeafe;color:#1e40af}}
.badge.stage{{background:#ede9fe;color:#5b21b6}} .badge.muted{{color:#666}}
.small{{color:#666;font-size:12px;margin-top:.2rem}}
</style></head><body>
<h1>Agent Catalog</h1><p class="sub">Generated {cat["generated_at"][:19]} · {len(cat["agents"])} agents · {len(cat["tools"])} approved tools · {len(cat["teams"])} teams</p>
<table><thead><tr><th>Agent</th><th>Team / owner</th><th>Stage</th><th>Model tier</th><th>Tools</th><th>Surfaces</th><th>Policy</th><th>Latest eval</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p class="small">Independent demonstration built on LangChain, LangGraph, Deep Agents, and LangSmith. Not an official LangChain product.</p>
</body></html>"""


def write_catalog(out_dir: Path | None = None) -> tuple[Path, Path]:
    out = out_dir or CATALOG_DIR
    out.mkdir(parents=True, exist_ok=True)
    cat = build_catalog()
    j = out / "catalog.json"
    h = out / "index.html"
    j.write_text(json.dumps(cat, indent=2))
    h.write_text(render_html(cat))
    return j, h
