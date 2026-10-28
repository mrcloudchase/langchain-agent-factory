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

from agent_factory.paths import CATALOG_DIR
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
    template: Annotated[
        str | None, typer.Option(help="template key; see `factory templates`")
    ] = None,
    purpose: Annotated[str | None, typer.Option(help="what the agent does and for whom")] = None,
):
    """Scaffold a new agent from a template: spec, instructions, and a starter eval dataset."""
    from agent_factory.scaffold import (
        TEMPLATES,
        build_spec_dict,
        create_agent,
        starter_examples,
        template_instructions,
    )

    if template and template not in TEMPLATES:
        console.print(f"[red]unknown template '{template}'[/red]; run `factory templates`")
        raise typer.Exit(2)
    display = display or name.replace("_", " ").title()
    purpose = purpose or (
        TEMPLATES[template].summary
        if template
        else "Describe in one or two sentences what this agent does and for whom."
    )
    spec_dict = build_spec_dict(
        name=name, display_name=display, team=team, owner=owner, purpose=purpose, template=template
    )
    try:
        spec, policy = create_agent(
            spec_dict,
            template_instructions(template, display),
            starter_examples(name, template, None),
        )
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if not policy.ok:
        console.print("[red]Not created: the spec violates policy[/red]")
        for v in policy.errors:
            console.print(f"  [red]{v.rule}[/red]: {v.message}")
        raise typer.Exit(1)
    console.print(f"[green]Created {spec.directory}[/green]")
    for v in policy.warnings:
        console.print(f"  [yellow]warning[/yellow] {v.rule}: {v.message}")
    console.print(f"Next: edit AGENTS.md and evals/dataset.jsonl, then `factory eval run {name}`.")


@app.command()
def templates():
    """List self-service templates."""
    from agent_factory.scaffold import list_templates

    table = Table()
    for col in ("key", "team", "tools", "approval", "summary"):
        table.add_column(col)
    for t in list_templates():
        table.add_row(
            t["key"],
            t["team"],
            ", ".join(t["tools"]) or "-",
            ", ".join(t["approve"]) or "-",
            t["summary"],
        )
    console.print(table)


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


@app.command("console")
def console_cmd():
    """Print where the console is served (it runs inside the Agent Server)."""
    from agent_factory.surfaces import deployment_url

    console.print(
        "The console is served by the Agent Server. Start it with `langgraph dev`, then open:"
    )
    console.print(f"  {deployment_url()}/console")


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
