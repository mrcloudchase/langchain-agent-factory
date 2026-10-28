# LangChain product map for Professional Services work

*As of 2026-10-28, from official docs and pricing pages. Plan details and beta labels change; re-check before quoting to a customer.*

The question this answers: for each LangChain product, what does it do, what does a customer still have to build around it, and where does a deployed engineer earn their keep. The last column is the engagement work. The "factory" column says how this repository touches it.

## The map in one table

| Product | What it is | What the customer still has to build | Factory today |
|---|---|---|---|
| LangChain (OSS) | `create_agent`: a minimal agent harness with middleware; one model interface via `init_chat_model`; tools as functions | Which middleware the org mandates; tool conventions; model tier policy | Org middleware stack; model tiers in the registry |
| LangGraph (OSS) | Low-level orchestration runtime: durable execution, checkpoints, interrupts, streaming, store; mixes deterministic steps with model steps | The workflows themselves; when to use a workflow vs an agent | `factory` graph; workflow archetype is the next step |
| Deep Agents (OSS) | Batteries-included harness: planning, virtual filesystem, subagents, skills, memory, `interrupt_on`; built on `create_agent` | Which built-ins to allow per agent; approval rules; subagent tool scoping | Harness builds every agent on it; filesystem modes; per-subagent middleware |
| LangSmith Observability | Traces, threads, dashboards, alerts, feedback, annotation queues, online evaluators; LangSmith Chat (formerly Polly) and the Insights Agent for trace analysis | Tagging conventions so traces answer org questions (team, agent, surface, cost center); alert thresholds; who reads them | Audit middleware; metadata on every surface's runs; harvest reads flagged runs |
| LangSmith Evaluation | Datasets, experiments, code and LLM-as-judge evaluators, multi-turn simulation, pairwise comparison, tuned evaluators (beta) | The datasets and rubrics; what "passing" means per agent; wiring evals into release | Eval gate with thresholds and baselines; dataset sync; experiments uploaded |
| Context Hub | Versioned prompts, instructions, skills, and tool definitions with staging and production labels and webhooks | Promotion discipline; which commit is live where | Promotion pushes the context bundle; label move is a documented UI step |
| LangSmith Deployment | Managed Agent Server: assistants, threads, runs, crons, store, checkpointer, `/mcp`, custom routes; cloud, hybrid, self-hosted, standalone | Surfaces into the org's tools; auth and identity; which agents share a deployment | Surfaces: webhook app mounted in the server, MCP, cron, Slack; console served inside it |
| Studio and Agent Chat UI | Studio: developer IDE over the Agent Server (graph and chat modes, threads, time travel, experiments). Agent Chat UI: open-source end-user chat that surfaces interrupted threads | Which UI each audience gets; approval routing | Console is the platform-team view; links out rather than rebuilding either |
| LangSmith Fleet | No-code agent builder for non-technical teams: templates, clone/run/edit permissions, two identity models, Agent Inbox, per-agent Slack bots; metered in LSUs | Where Fleet ends and code-first begins; a shared catalog and policy across both | Positioned as the code-first counterpart; catalog could list Fleet agents next |
| LangSmith Sandboxes | Managed microVM sandboxes: snapshots, mounts, auth proxy, restricted egress by default; Deep Agents backend gives `execute` and file tools | Egress allowlists; which agents may execute code; secrets via the auth proxy | Not used; engineering agent is read-only by design. Natural next step for a code-fixing agent |
| LangSmith Engine | Agent that scans traces, clusters issues, diagnoses against connected code, opens PRs, creates dataset examples, learns from triage; LSU-metered with spend limits | Repo connection; triage ownership; how proposed fixes enter the release process | Harvest loop is the manual version; Engine would feed the same pending-case path |
| Managed Deep Agents | Hosted Deep Agents from a project folder via the `mda` or `deepagents` CLI; sandboxes, memory, identity, Slack channels, crons, Context Hub sync managed; private or public beta, US only | Fit against a custom deployment; what to keep in code vs declare | Not used; the factory owns its harness. Worth a sentence in the limits |
| LLM Gateway | One endpoint for all providers using the LangSmith key; provider secrets in the workspace; fallbacks; model access policies by org, workspace, user, or key; spend limits and cost by user and model; beta | Model access policy and budgets per team | Model tiers and `params` in the registry do this locally; the Gateway is where it would live for real |
| Self-hosted LangSmith | Helm on Kubernetes; ClickHouse, Postgres, Redis, optional SmithDB and blob storage; optional Deployment, Fleet, Engine, Sandboxes, Gateway; Enterprise add-on | Everything the Deployed Architect role lists: cluster design, HA, secrets, SSO, upgrades | Out of scope on purpose; `langgraph.json` is deployment-agnostic |

## What each product means for an engagement

**LangChain, LangGraph, Deep Agents.** The customer picks a level: `create_agent` for a customizable loop, LangGraph when deterministic steps matter, Deep Agents for long-running work with files and subagents. PS value is in choosing the level per use case and in the middleware the org mandates. The factory's bet is Deep Agents as the default harness with LangGraph underneath for workflows.

**Observability.** Everything works out of the box; what customers lack is convention. Which metadata every run must carry, which alerts page a human, which annotation queue a team lead reviews weekly. The factory stamps agent, team, and surface on every run and emits audit lines, which is the convention made concrete.

**Evaluation.** This is the heaviest requirement in the Deployed Engineer posting, and it is where customers are weakest. They have no datasets, no rubric, and no gate. The factory's answer is a dataset per agent, four code evaluators every agent must pass, an optional judge, thresholds in the spec, and a baseline from production. Tuned evaluators and multi-turn simulation are the next things to adopt once a dataset exists.

**Context Hub.** Customers version code and forget prompts. Promotion that pushes the context bundle and moves the environment label is the discipline. The SDK pushes commits; moving the label is still a UI step, which we note.

**Deployment.** The Agent Server already exposes REST, MCP, crons, and custom routes. Customers need the doors opened in the right places with the right identity. The surfaces model in the spec, and the rule that user-scoped tools cannot be reached from unattended surfaces, is the PS layer. Auth on the server is the first thing a real engagement adds.

**Studio, Agent Chat UI, Agent Inbox, console.** Three audiences: developers (Studio), end users (Chat UI), and approvers (Inbox). The platform team is a fourth audience with no product view, which is why the factory's console exists and why it links out instead of duplicating.

**Fleet.** The product for non-technical creators. The engagement question is governance across both populations: a Fleet agent and a code-first agent should appear in one catalog under one policy. That is a real gap and a small build.

**Sandboxes.** The safe way to let an agent run code. Any engagement with a coding or data-processing agent should start here rather than with shell access. Restricted egress by default is a selling point for security teams.

**Engine.** Automates the harvest loop the factory does by hand: issues from traces, fixes as PRs, examples into datasets. PS value is connecting it to the customer's repo and deciding how its PRs enter release. The factory's pending-case path is the manual on-ramp.

**Managed Deep Agents.** For customers who do not want to own a harness at all. Trade control for speed. Beta and US-only today, so it is an option to mention, not a foundation to build on.

**LLM Gateway.** Model access policy, fallbacks, and spend limits as a service. The factory's model tiers are the local version; in a real engagement the tier would name a Gateway model and the budget would live there.

**Self-hosted.** The Deployed Architect's lane: Kubernetes, datastores, HA, SSO. A Deployed Engineer should know the component list and the plan boundary (Enterprise add-on) and hand the rest over.

## Plan boundaries that shape proposals

| | Developer | Plus | Enterprise |
|---|---|---|---|
| Price | free, 1 seat | $39/seat/month | custom, annual |
| Traces | 5k/month, 14-day retention | 10k/month | custom |
| Deployment | none | one small serverless included | hybrid or self-hosted |
| Fleet | 7 LSUs/month | 37 LSUs/month | custom |
| Engine | not listed | metered in LSUs | from committed credits |
| Sandboxes | 8 LSUs, 10 sandboxes | 8 LSUs free then metered | custom |
| LLM Gateway | credits, pay as you go | controls included | custom |
| Identity | Google/GitHub SSO | same, plus org roles | SSO, RBAC, ABAC, SCIM |

Practical reading: a proof of value runs on Developer plus `langgraph dev`; a pilot with a hosted deployment needs Plus; anything with self-hosting, SSO, or data residency in the customer's cloud is Enterprise and brings the Deployed Architect in.

## Where the factory sits

The products cover build, test, deploy, and monitor for one agent at a time, and Fleet covers no-code creation. What they leave to the customer is the organizational layer: who may use which tool, what every agent must pass before production, where it may be embedded and as whom, and one place to see all of it. That layer is customer-specific by nature, which is why it is Professional Services work rather than product, and it is what this repository demonstrates.

## Sources

Official pages read on 2026-10-28: the LangSmith platform overview, Observability, Deployment, Agent Server, Sandboxes, Engine, Studio, self-hosted LangSmith, LangChain and LangGraph overviews, Deep Agents overview, Managed Deep Agents overview, Fleet, Context Hub, LLM Gateway pages, the pricing page, and the LangSmith Chat (Polly) and Insights Agent announcements.
