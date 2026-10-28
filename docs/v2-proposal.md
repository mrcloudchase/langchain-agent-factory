# Agent Factory v2: proposal

*A net-new build on a new branch that replaces main when done. This document is the reference for that build.*

## What it is

A platform where an organization defines what an agent is and how it reaches production, and teams create agents from those definitions in a console. It runs on LangChain's products and names each one it leans on. It does not rebuild Studio, Agent Chat UI, the Agent Inbox, Fleet, the LLM Gateway, or Engine.

## The objects

Four the organization owns, one that teams create.

| Object | Owner | What it holds |
|---|---|---|
| Archetype | platform (built in) | `workflow`: fixed steps with the model inside them, compiles to a LangGraph graph. `agent`: the model decides, compiles to a Deep Agent |
| Template | platform or a team lead | archetype, parameters the user fills, default tools, required approvals, evaluators and thresholds, allowed surfaces, the process it must follow, starter examples |
| Tool catalog | engineering | published tools with risk, scope (user or service), allowed teams, approval requirement |
| Process | platform | stages and gates as data: which checks, which approver role, what budget, per transition |
| Instance | a team | a template plus parameters. The spec is generated from it, never hand-written |

## Repository structure

```
agent-factory/
  README.md
  pyproject.toml
  langgraph.json                      one generic `factory` graph + nothing else to register
  org/                                the organization's definitions; the platform team owns this directory
    teams.yaml                        teams, leads, cost centers
    models.yaml                       model tiers with pinned params (local stand-in for the LLM Gateway)
    policy.yaml                       which rules are errors vs warnings, limits ceilings
    tools/catalog.yaml                published tools: name, impl, risk, scope, teams, approval
    processes/
      standard.yaml                   dev -> staging (policy, evals) -> production (evals, approver: team_lead, budget)
      regulated.yaml                  adds a second approver and a frozen dataset
    templates/
      claims_processing/              template.yaml, steps.yaml (workflow), instructions.md, examples.jsonl
      support_triage/
      research_brief/
      document_review/
      judge/
      meeting_actions/
  agents/                             instances; teams own their folder
    claims_intake/
      instance.yaml                   template: claims_processing, team, owner, parameters, tools, surfaces
      spec.generated.yaml             written by the factory; reviewable, never edited by hand
      evals/dataset.jsonl             starter examples from the template + the team's own
      evals/baseline.json             from the last passing production promotion
  src/factory/
    core/                             archetype.py, template.py, instance.py, spec.py, process.py, policy.py, registry.py
    build/                            agent_harness.py (Deep Agents), workflow_compiler.py (LangGraph), middleware.py, models.py
    evals/                            runner.py, evaluators.py, gate.py
    lifecycle/                        promote.py, ledger.py, feedback.py, catalog.py
    surfaces/                         webhook.py, mcp.py, cron.py, slack.py
    console/
      api/                            routers: catalog, agents, create, approvals, gate, promote, admin
      ui/                             static app, no build step
      auth.py                         roles: platform, builder, approver, viewer (Agent Server auth block)
    cli/                              `factory` commands mirroring the console
    tools/                            implementations referenced by org/tools/catalog.yaml
    graphs.py                         the `factory` graph: configurable.agent -> build from instance
  data/                               knowledge base, fixtures, sample traces
  tests/
  docs/                               engagement brief, architecture, product map, tradeoffs, demo script
  .github/workflows/ci.yml            lint, tests, policy on every instance, gate on every instance, offline
```

Two rules make this safe for non-technical creators: instances are data and specs are generated; policy runs before any file is written.

## Console: the experience

Four roles: **platform** (owns `org/`), **builder** (creates and iterates instances for their team), **approver** (resolves runtime approvals and promotion approvals for their team), **viewer** (leadership; reads the catalog).

### Screens

**1. Catalog (home).** Every agent as a card or row: name, team, owner, archetype, stage, surfaces, policy status, latest gate score, cost this week. Filters by team and stage. Leadership's one page.

**2. Create (wizard).**
- *Step 1, choose a template.* Cards grouped Workflow and Agent. Each card says in plain words what it does, where it pauses for a human, which gates it must pass, and which surfaces it may use.
- *Step 2, configure.* A form generated from the template's parameters: purpose, the plain-language rules for each workflow step or the instructions for an agent, inputs. Tools from the catalog, already filtered to the team, with sensitive ones showing the approval requirement. Surfaces from the allowed list.
- *Step 3, examples.* Three request-and-expected-answer pairs. These become the eval set. The template's starter examples are shown and can be kept.
- *Step 4, review.* The generated spec, the policy result inline, and the process the agent will follow drawn as a pipeline. Create is disabled until policy passes.

**3. Agent page.** The pipeline bar across the top: dev, staging, production, each stage showing its gates and their state (policy passed, evals 0.95 against 0.90, approval waiting on the team lead). Tabs:
- *Try it*: a chat that runs the agent; pauses appear inline with approve and reject.
- *Evals*: the dataset, run the gate, history with links to LangSmith experiments, pending cases harvested from traces with accept and edit.
- *Approvals*: runtime actions waiting on a human for this agent.
- *Surfaces*: where it is embedded and the exact wiring for each.
- *Activity*: recent runs from every surface, each linking to its LangSmith trace.
- *Versions*: ledger entries and Context Hub commits.
A **Request promotion** button runs the gates for the next stage and, when a human approval is required, puts it in the approver's inbox.

**4. Approvals inbox.** Two kinds in one list, filtered to what the viewer may approve: runtime actions (a refund, a comment) and promotion requests (claims_intake to production). Each shows the evidence: arguments for an action, the gate report for a promotion.

**5. Admin (platform role).** Templates: list, publish, retire. Tool catalog: publish a tool with risk, scope, teams, approval. Processes: edit stages and gates. Teams and roles. Policy settings.

### Two walkthroughs

*A claims operations lead, no code.* Opens Create, picks Claims processing (Workflow). Fills the intake fields and the decision rules in plain language. Sees `record_claim_decision` marked "always pauses for a human". Adds three example claims. Review shows policy ok and the standard process. Creates. Tries it with a $3,100 theft claim; it pauses on refer; she approves. Requests promotion to staging; the gate passes; the pipeline advances. Requests production; her team lead gets the approval with the gate report attached.

*A platform engineer publishing a tool.* Writes the function, adds it to the catalog with risk high, scope service, teams operations, approval required. From that moment the tool appears in the claims template picker for operations only, greyed for everyone else, and any instance using it is forced to list it under approvals.

## What it leans on, named

LangSmith Observability for traces (every run links out), Evaluation for experiments, Context Hub for versions, Deployment and the Agent Server for runtime and surfaces, the Agent Inbox and Studio for developer and approver views beyond the console, Fleet for non-technical creation outside the factory, the LLM Gateway for model policy in production (model tiers are the local stand-in), Engine for automated issue detection (the harvest loop is the manual on-ramp), Sandboxes for any template that executes code.

## Build order

1. Core objects and policy, with generated specs and offline mode.
2. Both archetypes: the Deep Agents harness and the workflow compiler. Claims processing as the first workflow.
3. Eval gate and process as data; promotion that reads the process.
4. The `factory` graph and surfaces.
5. Console: catalog, create wizard, agent page with pipeline, approvals inbox.
6. Admin screens and roles.
7. Docs, demo, recording.

Each step ships with tests and runs offline in CI. Live verification with DeepSeek and LangSmith at steps 3 and 5.

## Not in scope, stated

Real integrations beyond GitHub and Slack; per-user token flow into tools; cost accounting beyond budgets; multi-tenant memory namespaces; template authoring as a visual editor (templates are files the platform team edits). Each is listed in the tradeoffs doc as the next engagement work.
