# Engagement brief: Halcyon Logistics agent factory

*Written the way a Professional Services engagement would frame it. Halcyon Logistics is fictional; the problems are not.*

## Situation

Halcyon is a 2,400-person logistics company eight months into "doing agents". Three teams have shipped something:

- **Market Research** has a research assistant a contractor built on raw API calls. It is useful and nobody but the contractor can change it.
- **Customer Support** piloted an auto-reply bot that once offered a refund it was not allowed to give. The pilot was paused. The team still wants the triage help.
- **Engineering** has four internal scripts that call a model from the terminal. Two of them read the repo. None are traced.

Leadership asked a reasonable question: *how many agents do we run, who owns them, what can each one do, and how do we know any of them work?* Nobody could answer. The CTO's framing: "I don't want to stop teams building. I want to stop finding out about it afterwards."

## What they asked for

A way for teams to keep building agents for their own needs, on a foundation the platform team owns, with oversight that is real but does not require a central review of every prompt change.

## What we proposed

A code-first **agent factory** on the LangChain stack, delivered in a six-week co-build:

| Week | Outcome |
|---|---|
| 1 | Registry of approved tools, model tiers, and teams. Agree the ten policy rules with security and platform. |
| 2 | Shared harness on Deep Agents with org middleware (budgets, allowlist, audit, approvals). Migrate the research assistant as the first spec. |
| 3 | Eval gate: datasets, code evaluators, thresholds, baseline. CI runs it on every PR without secrets. |
| 4 | Support triage agent rebuilt as a spec, with `issue_refund` behind human approval and a webhook surface into the helpdesk. |
| 5 | Engineering assistant on MCP into the IDE. Promotion flow and Context Hub integration. Catalog. |
| 6 | Trace-to-dataset loop on live traffic. Handover: the platform team owns the registry and harness; teams own specs. |

Everything in this repository is the week-6 state of that plan, run offline so it can be inspected without credentials.

## How the roles divide after handover

| Who | Owns | Touches |
|---|---|---|
| Platform team | `registry/`, `src/agent_factory/`, policy rules, CI | Adds tools and tiers; tightens or relaxes rules; reviews promotion to production |
| Team builder | `agents/<name>/agent.yaml`, `AGENTS.md`, `evals/dataset.jsonl` | Iterates locally, opens a PR, reads the gate result, requests promotion |
| Team lead | Approvals | Resolves `interrupt_on` pauses in the Agent Inbox; curates harvested eval cases |
| Leadership | Catalog | Reads `catalog/index.html`: owner, stage, surfaces, eval score per agent |

## What success looks like

- A new agent goes from `factory new` to staging in under a day without a platform ticket.
- No agent reaches production without a passing eval gate, and the gate is visible on the PR.
- Every sensitive action (money, external posts) pauses for a named human.
- The catalog answers the CTO's question in one page.
- When an agent misbehaves in production, the trace becomes an eval case within the week, and the next version cannot ship until it passes.

## What we told them it would not do

See [tradeoffs-and-limits.md](tradeoffs-and-limits.md). The short version: the factory constrains builders by design; the escape hatch is raw LangGraph for the one agent in ten that needs it, and that agent still goes through the gate.
