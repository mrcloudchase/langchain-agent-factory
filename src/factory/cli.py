"""`factory`: the platform team's and builders' command line. Mirrors the console."""

from __future__ import annotations

import json
import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from factory import config
from factory.org import User, load_org

app = typer.Typer(
    help="Agent Factory: templates, tools, and a path to production for every team.",
    no_args_is_help=True,
)
out = Console()
As = Annotated[str, typer.Option("--as", help="user id from org/teams.yaml")]
logging.getLogger("factory.audit").setLevel(logging.WARNING)


def _user(user_id: str) -> User:
    found = load_org().user(user_id)
    if found is None:
        out.print(f"[red]unknown user '{user_id}'[/red]")
        raise typer.Exit(2)
    return found


def _table(columns: list[str], rows: list[list[str]], title: str | None = None) -> None:
    table = Table(title=title)
    for c in columns:
        table.add_column(c)
    for r in rows:
        table.add_row(*r)
    out.print(table)


@app.command()
def check() -> None:
    """Check org/ as a whole: templates, catalog, processes, tiers, teams. Run in CI."""
    org = load_org()
    problems = org.problems()
    out.print(
        f"{len(org.templates)} templates · {len(org.tools)} tools · "
        f"{len(org.processes)} processes · {len(org.teams)} teams · {len(org.users)} people"
    )
    for p in problems:
        out.print(f"  [red]problem[/red] {p}")
    out.print(
        "[green]org is consistent[/green]"
        if not problems
        else f"[red]{len(problems)} problem(s)[/red]"
    )
    raise typer.Exit(1 if problems else 0)


@app.command()
def templates() -> None:
    """The organization's templates."""
    _table(
        ["template", "type", "teams", "process", "pauses for a person"],
        [
            [t.key, t.archetype, ", ".join(t.teams), t.process, ", ".join(t.approvals) or "-"]
            for t in load_org().templates.values()
        ],
    )


@app.command()
def tools() -> None:
    """The published tool catalog."""
    _table(
        ["tool", "teams", "sensitive", "acts as", "owner"],
        [
            [t.name, ", ".join(t.teams) or "all", "yes" if t.sensitive else "", t.acts_as, t.owner]
            for t in load_org().tools.values()
        ],
    )


@app.command()
def processes() -> None:
    """The paths to production."""
    for p in load_org().processes.values():
        steps = " -> ".join(
            f"{to} [{', '.join(t.checks + [f'{a} approval' for a in t.approvals])}]"
            for to, t in p.transitions.items()
        )
        out.print(f"[bold]{p.name}[/bold]: {p.stages[0]} -> {steps}\n  {p.description}")


@app.command()
def new(
    name: str,
    template: Annotated[str, typer.Option()],
    as_user: As,
    purpose: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Create an agent from a template. Policy runs before anything is written."""
    from factory.lifecycle.create import Refused, create

    try:
        agent = create(_user(as_user), name=name, template=template, purpose=purpose)
    except Refused as e:
        out.print("[red]refused[/red]")
        for v in e.violations:
            out.print(f"  {v.rule}: {v.message}")
        raise typer.Exit(1) from e
    out.print(f"[green]created {agent.name}[/green] from {agent.template} for {agent.team}")


@app.command("list")
def list_agents() -> None:
    """Every agent with its template, team, and stage."""
    from factory.lifecycle.catalog import catalog

    _table(
        ["agent", "template", "type", "team", "stage", "last gate"],
        [
            [
                c["name"],
                c["template"],
                c["archetype"],
                c["team"],
                c["pipeline"]["current"],
                "-" if not c["gate"] else ("pass" if c["gate"]["passed"] else "FAIL"),
            ]
            for c in catalog()
        ],
    )


@app.command()
def run(name: str, question: str, approve: bool = False, reject: bool = False) -> None:
    """Run an agent locally; approvals are answered here."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from factory.build import build
    from factory.evals.runner import trajectory
    from factory.spec import load_spec

    graph = build(load_spec(name), checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "cli"}}
    state = graph.invoke({"messages": [HumanMessage(content=question)]}, config=cfg)
    while state.get("__interrupt__"):
        requests = state["__interrupt__"][0].value["action_requests"]
        for r in requests:
            out.print(
                f"[yellow]waiting for approval:[/yellow] {r['name']}({json.dumps(r['args'])})"
            )
        ok = approve or (not reject and typer.confirm("Approve?", default=False))
        decision = (
            {"type": "approve"}
            if ok
            else {"type": "reject", "message": "Rejected by the operator."}
        )
        state = graph.invoke(Command(resume={"decisions": [decision] * len(requests)}), config=cfg)
    result = trajectory(state["messages"])
    out.print(
        f"[dim]tools: {', '.join(result['tool_calls']) or 'none'}[/dim]\n\n{result['answer']}"
    )


@app.command("eval")
def evaluate(name: str) -> None:
    """Run the eval gate."""
    from factory.evals.gate import run_gate
    from factory.spec import load_spec

    report = run_gate(load_spec(name))
    _table(
        ["evaluator", "mean", "threshold", "baseline", "result"],
        [
            [
                s.key,
                f"{s.mean:.2f}",
                f"{s.threshold:.2f}" if s.threshold is not None else "-",
                f"{s.baseline:.2f}" if s.baseline is not None else "-",
                "pass" if s.passed else f"FAIL {s.reason}",
            ]
            for s in report.scores
        ],
        title=f"{name} · {report.mode} · {len(report.cases)} cases"
        + (f" · {report.skipped} live-only skipped" if report.skipped else ""),
    )
    if report.experiment_url:
        out.print(f"experiment: {report.experiment_url}")
    raise typer.Exit(0 if report.passed else 1)


@app.command()
def promote(name: str, as_user: As) -> None:
    """Request promotion to the next stage of the agent's process."""
    from factory.lifecycle.promotion import Blocked, request

    try:
        outcome = request(name, _user(as_user))
    except Blocked as e:
        out.print(f"[red]blocked[/red] {e}")
        raise typer.Exit(1) from e
    out.print(
        f"{name} -> {outcome.to}: [bold]{outcome.status}[/bold]"
        + (f" (request {outcome.request['id']})" if outcome.request else "")
    )
    for note in outcome.notes:
        out.print(f"  {note}")


@app.command()
def approve(request_id: str, as_user: As, reject: bool = False, comment: str = "") -> None:
    """Approve or reject a promotion request."""
    from factory.lifecycle.promotion import Blocked, decide

    try:
        outcome = decide(request_id, _user(as_user), not reject, comment)
    except Blocked as e:
        out.print(f"[red]blocked[/red] {e}")
        raise typer.Exit(1) from e
    out.print(f"{outcome.agent} -> {outcome.to}: [bold]{outcome.status}[/bold]")
    for note in outcome.notes:
        out.print(f"  {note}")


@app.command()
def surfaces(name: str) -> None:
    """Where the agent is reachable and how."""
    from factory.spec import load_spec
    from factory.surfaces import describe

    for s in describe(load_spec(name)):
        out.print(f"[bold]{s['kind']}[/bold] ({s['identity']}): {s['how']}")


@app.command()
def schedule(name: str, url: str = "http://localhost:2024") -> None:
    """Register the agent's cron surface on an Agent Server."""
    import asyncio

    from langgraph_sdk import get_client

    from factory.server.runs import assistant_id
    from factory.spec import load_spec

    spec = load_spec(name)
    if spec.cron is None:
        out.print(f"[red]{name} has no cron surface[/red]")
        raise typer.Exit(1)

    async def _register():
        client = get_client(url=url)
        assistant = await assistant_id(client, name)
        return await client.crons.create(
            assistant,
            schedule=spec.cron.schedule,
            input={"messages": [{"role": "user", "content": spec.cron.question}]},
            metadata={"agent": name, "surface": "cron"},
        )

    cron = asyncio.run(_register())
    out.print(f"[green]scheduled[/green] {name} '{spec.cron.schedule}' (cron {cron['cron_id']})")


@app.command()
def remove(name: str, as_user: As) -> None:
    """Remove an agent and its history. Platform team only."""
    from factory.agents import store
    from factory.lifecycle.ledger import ledger

    if _user(as_user).role != "platform":
        out.print("[red]only the platform team removes agents[/red]")
        raise typer.Exit(1)
    store().delete(name)
    ledger().forget(name)
    out.print(f"removed {name}")


@app.command()
def mode() -> None:
    """Show whether models and HTTP are live or replayed."""
    out.print(
        "offline: scripted models, recorded HTTP" if config.offline() else "live models and HTTP"
    )
    out.print("LangSmith: " + ("on" if config.langsmith() else "off"))
