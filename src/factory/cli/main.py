"""`factory` CLI. Mirrors the console so everything is scriptable and testable."""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="Agent Factory: org-defined templates, policy, gates, promotion, surfaces.",
    no_args_is_help=True,
)
console = Console()


def _quiet() -> None:
    logging.getLogger("factory.audit").setLevel(
        logging.DEBUG if os.environ.get("FACTORY_AUDIT") else logging.WARNING
    )


def _spec(name: str):
    from factory.core.spec import load_spec

    try:
        return load_spec(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e


@app.command()
def templates():
    """List the organization's templates."""
    from factory.core.template import list_templates

    t = Table()
    for c in ("key", "archetype", "team", "process", "pauses for human", "summary"):
        t.add_column(c)
    for tpl in list_templates():
        t.add_row(
            tpl.key,
            tpl.archetype,
            tpl.team_default,
            tpl.process,
            ", ".join(tpl.oversight.required_approve) or "-",
            tpl.summary,
        )
    console.print(t)


@app.command()
def tools():
    """List the published tool catalog."""
    from factory.core.registry import load_registry

    t = Table()
    for c in ("tool", "risk", "scope", "sensitive", "teams", "owner"):
        t.add_column(c)
    for e in load_registry().tools.values():
        t.add_row(
            e.name,
            e.risk,
            e.scope,
            "yes" if e.sensitive else "",
            ", ".join(e.teams) or "all",
            e.owner,
        )
    console.print(t)


@app.command()
def new(
    name: str,
    template: Annotated[str, typer.Option(help="template key")],
    owner: Annotated[str, typer.Option(help="accountable human")],
    team: Annotated[str | None, typer.Option()] = None,
    display: Annotated[str | None, typer.Option()] = None,
    purpose: Annotated[str | None, typer.Option()] = None,
    param: Annotated[list[str] | None, typer.Option(help="key=value, repeatable")] = None,
):
    """Create an agent from a template. Policy runs before anything is kept."""
    from factory.lifecycle.create import create_instance

    params = dict(p.split("=", 1) for p in (param or []))
    try:
        inst, spec, policy = create_instance(
            name=name,
            template=template,
            owner=owner,
            team=team,
            display_name=display,
            purpose=purpose,
            parameters=params,
            created_by=owner,
        )
    except (FileExistsError, KeyError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if not policy.ok:
        console.print("[red]Not created: policy violations[/red]")
        for v in policy.errors:
            console.print(f"  {v.rule}: {v.message}")
        raise typer.Exit(1)
    console.print(
        f"[green]Created {inst.directory}[/green] ({spec.archetype} from '{template}', process '{spec.process}')"
    )
    for v in policy.warnings:
        console.print(f"  [yellow]warning[/yellow] {v.rule}: {v.message}")


@app.command()
def validate(name: Annotated[str | None, typer.Argument()] = None):
    """Policy check on one agent or all."""
    from factory.core.instance import list_instances
    from factory.core.policy import check_spec
    from factory.core.spec import load_spec

    names = [name] if name else [i.name for i in list_instances()]
    failed = False
    for n in names:
        r = check_spec(load_spec(n))
        console.print(f"{n}: " + ("[green]ok[/green]" if r.ok else "[red]violations[/red]"))
        for v in r.violations:
            console.print(
                f"  [{'red' if v.severity == 'error' else 'yellow'}]{v.severity}[/] {v.rule}: {v.message}"
            )
        failed |= not r.ok
    raise typer.Exit(1 if failed else 0)


@app.command()
def run(name: str, question: str, approve: bool = False, reject: bool = False):
    """Run an agent locally; approvals are answered in the terminal."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from factory.build import build
    from factory.build.models import is_offline

    _quiet()
    spec = _spec(name)
    if is_offline():
        console.print("[yellow]offline mode: replaying scripted trajectories[/yellow]")
    g = build(spec, checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "cli"}}
    state = g.invoke({"messages": [HumanMessage(content=question)]}, config=cfg)
    while state.get("__interrupt__"):
        reqs = state["__interrupt__"][0].value["action_requests"]
        decisions = []
        for r in reqs:
            console.print(
                f"[yellow]Approval required:[/yellow] {r['name']}({json.dumps(r['args'])})"
            )
            ok = True if approve else False if reject else typer.confirm("Approve?", default=False)
            if reject:
                console.print("[red]Rejected by operator (--reject).[/red]")
            decisions.append(
                {"type": "approve"}
                if ok
                else {"type": "reject", "message": "Rejected by operator."}
            )
        state = g.invoke(Command(resume={"decisions": decisions}), config=cfg)
    for m in state["messages"]:
        if m.type == "tool":
            console.print(f"[dim]tool {m.name}: {str(m.content)[:160]}[/dim]")
    if spec.archetype == "workflow":
        for k, v in state.get("outputs", {}).items():
            console.print(f"[cyan]{k}[/cyan]: {str(v)[:200]}")
    console.print("\n" + str(state["messages"][-1].content))


@app.command("eval")
def eval_cmd(name: Annotated[str | None, typer.Argument()] = None, verbose: bool = False):
    """Run the eval gate for one agent or all. Exit 1 on any failure."""
    from factory.core.instance import list_instances
    from factory.evals import run_gate

    _quiet()
    names = [name] if name else [i.name for i in list_instances()]
    failed = False
    for n in names:
        report = run_gate(_spec(n))
        t = Table(title=f"{n} · {report.mode} · {report.examples} examples")
        for c in ("evaluator", "mean", "threshold", "baseline", "result"):
            t.add_column(c)
        for s in report.scores:
            t.add_row(
                s.key,
                f"{s.mean:.2f}",
                "-" if s.threshold is None else f"{s.threshold:.2f}",
                "-" if s.baseline is None else f"{s.baseline:.2f}",
                "[green]pass[/green]" if s.passed else f"[red]fail[/red] {s.reason}",
            )
        console.print(t)
        if report.experiment_url:
            console.print(f"  experiment: {report.experiment_url}")
        if verbose:
            for d in report.details:
                low = [k for k, v in d["scores"].items() if v < 1.0]
                console.print(
                    f"  {'[red]x[/red]' if low else '[green]ok[/green]'} {d['example']}: {d['question']!r} tools={d['tool_calls']} interrupts={d['interrupts']}"
                )
                if low:
                    console.print(f"      scores={d['scores']} answer={d['answer'][:200]!r}")
        failed |= not report.passed
    raise typer.Exit(1 if failed else 0)


@app.command()
def promote(
    name: str,
    to: Annotated[str | None, typer.Option()] = None,
    by: Annotated[str | None, typer.Option(help="requesting user id")] = None,
):
    """Request promotion to the next stage. Runs the process gates; waits on approvers if required."""
    from factory.lifecycle.promote import PromotionBlocked, request_promotion

    _quiet()
    try:
        res = request_promotion(_spec(name), to, requested_by=by)
    except PromotionBlocked as e:
        console.print(f"[red]Promotion blocked:[/red] {e}")
        raise typer.Exit(1) from e
    color = "green" if res.status == "promoted" else "yellow"
    console.print(f"[{color}]{name} -> {res.to}: {res.status}[/{color}]")
    for n in res.notes:
        console.print(f"  - {n}")
    if res.request and res.status == "pending":
        console.print(
            f"  request id: {res.request['id']}  (approve with: factory approve {name} {res.request['id']} --as <user>)"
        )


@app.command()
def approve(
    name: str,
    request_id: str,
    as_user: Annotated[str, typer.Option("--as")],
    reject: bool = False,
    comment: str = "",
):
    """Approve or reject a pending promotion request as a user."""
    from factory.lifecycle.promote import PromotionBlocked, approve_promotion

    try:
        res = approve_promotion(
            _spec(name),
            request_id,
            user_id=as_user,
            decision="reject" if reject else "approve",
            comment=comment,
        )
    except PromotionBlocked as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"{name} -> {res.to}: {res.status}")
    for n in res.notes:
        console.print(f"  - {n}")


@app.command()
def pipeline(name: str):
    """Show the agent's process: stages, current stage, gates, pending requests."""
    from factory.lifecycle.promote import plan

    console.print_json(json.dumps(plan(_spec(name)), default=str))


@app.command("list")
def list_cmd():
    """List agents with team, archetype, stage, and latest gate."""
    from factory.lifecycle.catalog import build_catalog

    t = Table()
    for c in ("agent", "archetype", "team", "stage", "process", "surfaces", "policy", "gate"):
        t.add_column(c)
    for a in build_catalog()["agents"]:
        ev = a["eval"]
        t.add_row(
            a["name"],
            a["archetype"],
            a["team"],
            a["stage"],
            a["process"],
            ", ".join(s["kind"] for s in a["surfaces"]),
            "ok" if a["policy"]["ok"] else "VIOLATIONS",
            "-" if not ev else ("pass" if ev["passed"] else "FAIL"),
        )
    console.print(t)


@app.command()
def surfaces(name: str):
    """Show how each declared surface is wired."""
    from factory.surfaces import describe_surfaces

    for s in describe_surfaces(_spec(name)):
        console.print(f"[bold]{s['kind']}[/bold] ({s['identity']}): {s['how']}")


@app.command()
def harvest(name: Annotated[str | None, typer.Argument()] = None):
    """Turn flagged traces into pending eval cases."""
    from factory.core.instance import list_instances
    from factory.lifecycle.feedback import harvest as do_harvest
    from factory.lifecycle.feedback import pending_path

    for n in [name] if name else [i.name for i in list_instances()]:
        spec = _spec(n)
        added = do_harvest(spec)
        console.print(f"{n}: {len(added)} new pending case(s) -> {pending_path(spec)}")


@app.command()
def remove(name: str, yes: bool = False):
    """Delete an agent instance and its ledger entries."""
    import shutil

    from factory.lifecycle import ledger

    spec = _spec(name)
    if not yes and not typer.confirm(f"Delete {spec.directory}?"):
        raise typer.Exit(1)
    shutil.rmtree(spec.directory, ignore_errors=True)
    ledger.forget(name)
    console.print(f"[green]removed {name}[/green]")


@app.command()
def clean():
    """Remove generated state (.factory, catalog)."""
    import shutil

    from factory.paths import CATALOG_DIR, STATE_DIR

    for d in (STATE_DIR, CATALOG_DIR):
        shutil.rmtree(d, ignore_errors=True)
    console.print("[green]clean[/green]")


if __name__ == "__main__":
    app()
