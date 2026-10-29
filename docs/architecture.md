# Architecture

Three kinds of state, owned by three kinds of people:

| State | Owner | Where | Changed by |
|---|---|---|---|
| The organization: teams, people, model tiers, tool catalog, processes, templates | Platform team | `org/` | Pull request; CI runs `factory check` |
| Agents: a template plus a team's choices (name, purpose, parameters, tools, surfaces) and its eval dataset | The building team | `agents/<name>/` | Console or CLI, through policy |
| Lifecycle: stage per agent, promotion requests and approvals, gate reports | The process | `.factory/` | Promotion and approval only |

LangSmith holds what it is best at: traces, datasets and experiments, feedback, and Context Hub versions. The Agent Server holds assistants, threads, runs, interrupts and crons.

## From template to running agent

```
org/templates/support_agent/          agents/billing_support/agent.yaml
  template.yaml  ─────────┐            (name, team, purpose, parameters,
  instructions.md         │             tools, surfaces)
  examples.jsonl          │                      │
                          ▼                      ▼
                   policy.check(agent, org)  ── refuses before anything is written
                          │
                   spec.materialize(agent, org)
                          │  instructions rendered with parameters
                          │  approvals = template approvals ∩ chosen tools
                          │  model, limits, thresholds, process from the template
                          ▼
                   build(spec)
                   ├─ agent template    → create_deep_agent(tools, interrupt_on=approvals,
                   │                                        middleware=org_middleware)
                   └─ workflow template → StateGraph: one create_agent node per step,
                                          each with org middleware and HITL for gated tools
```

`graph.py` exposes one graph, `factory`, to the Agent Server. Each agent is an assistant on that graph with `configurable.agent=<name>`; the graph factory builds (and caches) the agent from its spec, rebuilding when `agent.yaml` changes, so a reconfigured agent needs no server restart.

Every agent and every workflow step gets the same middleware, which teams cannot remove:

- `ModelCallLimitMiddleware` and `ToolCallLimitMiddleware` with the template's limits;
- `ToolAllowlist`, which refuses any tool outside the approved set at call time and returns `BLOCKED_BY_POLICY` (the model only sees approved tools, so this is defense in depth);
- `Audit`, one structured log line per tool call.

## Templates make invalid agents unrepresentable

An agent records choices, never rules. There is no field for "approvals" on an agent: approvals come from the template, so a builder cannot remove the pause on `issue_refund`. Invariants are checked at three levels:

| Level | Checked when | Examples |
|---|---|---|
| Template | Loading `org/` | approvals name template tools; a cron surface has a schedule; workflow steps use exactly the template's tools |
| Organization | `factory check` in CI | templates name real teams, processes and tiers; every tool is in the catalog; every sensitive tool requires approval; evaluators exist |
| Agent | Create and reconfigure | template offered to the team; tools allowed for the team; surfaces allowed by the template; a tool that acts as the user is never reachable from an unattended surface (webhook, cron); required parameters filled; the person may build for the team |

## Promotion

Processes are data. `standard`: policy and evals to reach staging; evals plus a team approver to reach production. `regulated`: the same plus a platform approver.

```
request(name, by)
  ├─ by may build for the agent's team?            no → Blocked
  ├─ policy.check                                   violations → Blocked
  ├─ run_gate(spec)                                 fails → Blocked (report attached)
  ├─ transition needs approvals?                    no → promote
  └─ open a request with the evidence (policy, scores, experiment URL)

decide(request, by, approve)
  ├─ requester, or someone who already approved?    → Blocked
  ├─ the next missing approval this person may give (team approver, or platform)
  └─ all approvals in → promote

promote
  ├─ final stage: save the gate scores as the production baseline
  ├─ push AGENTS.md and agent.yaml to Context Hub, tagged with the stage
  └─ record the stage, evidence and links in the ledger
```

## The gate

`evals/gate.py` runs the agent's dataset: the template's cases (copied at creation), cases the builder added, and cases accepted from flags. Live with LangSmith, the dataset is synced and run through `langsmith.evaluate`, so each gate is an experiment with per-case traces. Four code evaluators score each run:

| Evaluator | Passes when |
|---|---|
| `tool_usage` | the expected tools were called and forbidden tools were not |
| `answer_contains` | the answer contains the phrases the case requires |
| `oversight` | sensitive actions paused for a person exactly when the case says they should |
| `policy_compliance` | no tool call was blocked by the allowlist |

A score fails below the template's threshold, or when it drops more than the template's tolerance below the production baseline.

## Runtime

The console and the webhook are FastAPI routes mounted in the Agent Server (`langgraph.json` → `http.app`). They start runs with the async SDK against the same server, so console runs, webhook runs, MCP calls and crons all land as threads tagged with `agent`, `surface` and `user`. Blocking work (disk, gates) runs in threads so the server's event loop never blocks.

A paused run is a thread in the `interrupted` state. The Approvals page lists those threads; approving resumes the run with `Command(resume={"decisions": [...]})`. Only people who may build for the agent's team can decide.

## Feedback

```
someone reads a bad answer ── Flag ──► pending case (question, observed answer, note)
                                       + LangSmith feedback "flagged" = 0 on the run
builder writes what a correct answer must contain ── Accept ──► dataset row (split: flagged)
                                                     every later gate runs it
```

## Offline mode

With no provider key (or `FACTORY_OFFLINE=1`), a scripted model replays each template case's recorded trajectory, and HTTP tools replay recorded responses from `data/fixtures/http/`. Policy, build, interrupts, gates and promotion all run for real; only the model and the network are replaced. Cases without a recording (builder-written or flagged) run live only and are counted as skipped offline. `FACTORY_RECORD=1` records new HTTP fixtures.
