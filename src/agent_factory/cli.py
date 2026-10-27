"""`factory` CLI: the builder's and platform team's interface to the factory."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agent_factory.paths import AGENTS_DIR, CATALOG_DIR
from agent_factory.spec import AgentSpec, list_specs, load_spec

app = typer.Typer(
    help="Agent Factory: build, govern, evaluate, promote, and place agents.", no_args_is_help=True
)
evals_app = typer.Typer(help="Evaluation gate commands.")
feedback_app = typer.Typer(help="Trace-to-dataset feedback loop.")
surfaces_app = typer.Typer(help="Embed agents where teams work.")
app.add_typer(evals_app, name="eval")
app.add_typer(feedback_app, name="feedback")
app.add_typer(surfaces_app, name="surfaces")
console = Console()

TEMPLATE_SPEC = """name: {name}
display_name: {display}
team: {team}
owner: {owner}
purpose: >-
  Describe in one or two sentences what this agent does and for whom. The factory
  requires at least twenty characters here.
model_tier: standard
tools: [knowledge_search]
oversight:
  approve: []
limits:
  max_model_calls: 10
  max_tool_calls: 12
surfaces:
  - kind: chat
filesystem: scratch
evals:
  dataset: evals/dataset.jsonl
  thresholds:
    - {{evaluator: tool_usage, min_score: 0.9}}
    - {{evaluator: policy_compliance, min_score: 1.0}}
    - {{evaluator: oversight, min_score: 1.0}}
    - {{evaluator: answer_contains, min_score: 0.8}}
tags: []
"""

TEMPLATE_INSTRUCTIONS = """# {display}

Describe how this agent should behave. Be specific about which tool to use for what,
what it must never do, and how to end a response.
"""

TEMPLATE_EXAMPLE = {
    "id": "{name}-001",
    "inputs": {"question": "Replace with a realistic request"},
    "outputs": {
        "expected_tools": ["knowledge_search"],
        "forbidden_tools": [],
        "must_contain": [],
        "expects_approval": False,
        "reference": "What a correct answer must convey.",
    },
    "offline_trajectory": [
        {"tool": "knowledge_search", "args": {"query": "replace me"}},
        {"answer": "Replace with the expected final answer."},
    ],
    "metadata": {"split": "core"},
}


def _quiet() -> None:
    logging.getLogger("agent_factory.audit").setLevel(
        logging.DEBUG if os.environ.get("FACTORY_AUDIT") else logging.WARNING
    )


def _spec(name: str) -> AgentSpec:
    try:
        return load_spec(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e


@app.command()
def new(
    name: Annotated[str, typer.Argument(help="snake_case agent name")],
    team: Annotated[str, typer.Option(help="owning team from registry/teams.yaml")],
    owner: Annotated[str, typer.Option(help="accountable human (email)")],
    display: Annotated[str | None, typer.Option(help="display name")] = None,
):
    """Scaffold a new agent: spec, instructions, and a starter eval dataset."""
    d = AGENTS_DIR / name
    if d.exists():
        console.print(f"[red]{d} already exists[/red]")
        raise typer.Exit(1)
    (d / "evals").mkdir(parents=True)
    display = display or name.replace("_", " ").title()
    (d / "agent.yaml").write_text(
        TEMPLATE_SPEC.format(name=name, display=display, team=team, owner=owner)
    )
    (d / "AGENTS.md").write_text(TEMPLATE_INSTRUCTIONS.format(display=display))
    ex = json.loads(json.dumps(TEMPLATE_EXAMPLE).replace("{name}", name))
    (d / "evals" / "dataset.jsonl").write_text(json.dumps(ex) + "\n")
    console.print(
        f"[green]Created {d}[/green]. Next: edit agent.yaml and AGENTS.md, then `factory validate {name}`."
    )


@app.command()
def validate(name: Annotated[str | None, typer.Argument()] = None):
    """Check one agent (or all) against org policy and the registry."""
    from agent_factory.policy import check_spec

    specs = [_spec(name)] if name else list_specs()
    failed = False
    for spec in specs:
        r = check_spec(spec)
        status = "[green]ok[/green]" if r.ok else "[red]violations[/red]"
        console.print(f"{spec.name}: {status}")
        for v in r.violations:
            color = "red" if v.severity == "error" else "yellow"
            console.print(f"  [{color}]{v.severity}[/{color}] {v.rule}: {v.message}")
        failed |= not r.ok
    raise typer.Exit(1 if failed else 0)


@app.command()
def run(
    name: str,
    question: str,
    approve: Annotated[bool, typer.Option(help="auto-approve interrupts")] = False,
    reject: Annotated[bool, typer.Option(help="auto-reject interrupts")] = False,
):
    """Run an agent locally on one request, handling approvals in the terminal."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent_factory.harness import build_agent
    from agent_factory.models import is_offline

    _quiet()
    spec = _spec(name)
    if is_offline():
        console.print(
            "[yellow]offline mode: replaying scripted trajectories from the eval dataset[/yellow]"
        )
    agent = build_agent(spec, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "cli"}}
    state = agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)
    while state.get("__interrupt__"):
        reqs = state["__interrupt__"][0].value["action_requests"]
        decisions = []
        for r in reqs:
            console.print(
                f"[yellow]Approval required:[/yellow] {r['name']}({json.dumps(r['args'])})"
            )
            if approve:
                ok = True
            elif reject:
                ok = False
                console.print("[red]Rejected by operator (--reject).[/red]")
            else:
                ok = typer.confirm("Approve?", default=False)
            decisions.append(
                {"type": "approve"}
                if ok
                else {"type": "reject", "message": "Rejected by operator."}
            )
        state = agent.invoke(Command(resume={"decisions": decisions}), config=config)
    for m in state["messages"]:
        if m.type == "tool":
            console.print(f"[dim]tool {m.name}: {str(m.content)[:160]}[/dim]")
    console.print("\n" + str(state["messages"][-1].content))


@evals_app.command("run")
def eval_run(
    name: Annotated[str | None, typer.Argument()] = None,
    update_baseline: Annotated[bool, typer.Option(help="save scores as the new baseline")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="per-example detail")] = False,
):
    """Run the eval gate for one agent (or all). Exit code 1 if any gate fails."""
    from agent_factory.evals import run_gate
    from agent_factory.evals.gate import save_baseline

    _quiet()
    specs = [_spec(name)] if name else list_specs()
    failed = False
    for spec in specs:
        report = run_gate(spec)
        table = Table(
            title=f"{spec.name} · {report.mode} · {report.examples} examples", show_lines=False
        )
        for col in ("evaluator", "mean", "threshold", "baseline", "result"):
            table.add_column(col)
        for s in report.scores:
            table.add_row(
                s.key,
                f"{s.mean:.2f}",
                "-" if s.threshold is None else f"{s.threshold:.2f}",
                "-" if s.baseline is None else f"{s.baseline:.2f}",
                "[green]pass[/green]" if s.passed else f"[red]fail[/red] {s.reason}",
            )
        console.print(table)
        if report.experiment_url:
            console.print(f"  experiment: {report.experiment_url}")
        if verbose:
            for d in report.details:
                low = [k for k, v in d["scores"].items() if v < 1.0]
                mark = "[red]x[/red]" if low else "[green]ok[/green]"
                console.print(f"  {mark} {d['example']}: {d['question']!r}")
                console.print(
                    f"      scores={d['scores']} tools={d['tool_calls']} "
                    f"interrupts={d['interrupts']} blocked={d['blocked']}"
                )
                if low:
                    console.print(f"      answer: {d['answer'][:300]!r}")
        if update_baseline and report.passed:
            console.print(f"  baseline saved: {save_baseline(spec, report)}")
        failed |= not report.passed
    raise typer.Exit(1 if failed else 0)


@app.command()
def promote(
    name: str,
    to: Annotated[str, typer.Option(help="staging or production")] = "staging",
    skip_gate: Annotated[bool, typer.Option(help="dev/staging only")] = False,
):
    """Promote an agent to a stage. Runs policy and the eval gate first."""
    from agent_factory.promote import PromotionBlocked
    from agent_factory.promote import promote as do_promote

    _quiet()
    spec = _spec(name)
    try:
        res = do_promote(spec, to, skip_gate=skip_gate)  # type: ignore[arg-type]
    except PromotionBlocked as e:
        console.print(f"[red]Promotion blocked:[/red] {e}")
        raise typer.Exit(1) from e
    console.print(f"[green]{spec.name} promoted to {to}[/green]")
    for n in res.notes:
        console.print(f"  - {n}")
    if res.context_hub_url:
        console.print(f"  context hub: {res.context_hub_url}")


@feedback_app.command("harvest")
def feedback_harvest(
    name: Annotated[str | None, typer.Argument()] = None,
    source: Annotated[Path | None, typer.Option(help="JSONL of traces (offline)")] = None,
    hours: int = 168,
):
    """Turn flagged traces into pending eval cases for a human to curate."""
    from agent_factory.feedback import harvest, pending_path

    specs = [_spec(name)] if name else list_specs()
    for spec in specs:
        added = harvest(spec, source=source, hours=hours)
        console.print(f"{spec.name}: {len(added)} new pending case(s) -> {pending_path(spec)}")
        for row in added:
            console.print(
                f"  - {row['id']}: {row['inputs']['question'][:80]!r} ({row['metadata']['reason']})"
            )


@feedback_app.command("accept")
def feedback_accept(name: str, case_id: str):
    """Move a curated pending case into the live eval dataset."""
    from agent_factory.feedback import accept

    spec = _spec(name)
    try:
        moved = accept(spec, case_id)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if moved is None:
        console.print(f"[red]no pending case {case_id}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]{case_id} added to {spec.dataset_path}[/green]. Re-run `factory eval run {name}`."
    )


@app.command()
def catalog(out: Annotated[Path | None, typer.Option()] = None):
    """Generate the agent catalog (JSON + HTML)."""
    from agent_factory.catalog import write_catalog

    j, h = write_catalog(out or CATALOG_DIR)
    console.print(f"[green]catalog written[/green]: {j} and {h}")


@app.command("list")
def list_agents():
    """List agents with team, stage, surfaces, and latest eval."""
    from agent_factory.catalog import build_catalog

    cat = build_catalog()
    table = Table()
    for col in ("agent", "team", "stage", "tier", "tools", "surfaces", "policy", "eval"):
        table.add_column(col)
    for a in cat["agents"]:
        ev = a["eval"]
        table.add_row(
            a["name"],
            a["team"],
            a["stage"] or "-",
            a["model_tier"],
            str(len(a["tools"])),
            ", ".join(s["kind"] for s in a["surfaces"]),
            "ok" if a["policy_ok"] else "VIOLATIONS",
            "-" if not ev else ("pass" if ev["passed"] else "FAIL"),
        )
    console.print(table)


@surfaces_app.command("show")
def surfaces_show(name: str):
    """Show how each declared surface is wired for an agent."""
    from agent_factory.surfaces import describe_surfaces

    spec = _spec(name)
    for line in describe_surfaces(spec):
        console.print(line)


@surfaces_app.command("register-crons")
def surfaces_register_crons(
    name: Annotated[str | None, typer.Argument()] = None,
    url: Annotated[str | None, typer.Option(help="Agent Server URL")] = None,
    dry_run: bool = False,
):
    """Register cron surfaces on the Agent Server via the LangGraph SDK."""
    from agent_factory.surfaces.cron import register_crons

    specs = [_spec(name)] if name else list_specs()
    for spec in specs:
        for line in register_crons(spec, url=url, dry_run=dry_run):
            console.print(line)


@app.command()
def clean():
    """Remove generated state (ledger, reports, catalog)."""
    from agent_factory.paths import STATE_DIR

    for d in (STATE_DIR, CATALOG_DIR):
        if d.exists():
            shutil.rmtree(d)
    console.print("[green]clean[/green]")


@app.command("export-spec")
def export_spec(name: str):
    """Print the resolved spec as JSON (what the harness actually builds from)."""
    spec = _spec(name)
    console.print_json(json.dumps(spec.model_dump(), default=str))


if __name__ == "__main__":
    app()
