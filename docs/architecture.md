# Architecture

## One sentence

A team writes a spec; the factory validates it against the org registry, builds a Deep Agent with middleware the team cannot remove, refuses to promote it until its evals pass, places it on the surfaces it declared, and lists it in the catalog.

## The pipeline

```
agents/<name>/agent.yaml ──► policy.check_spec ──► harness.build_agent ──► evals.run_gate ──► promote ──► surfaces
        │                        │                       │                      │                │
   registry/*.yaml          Violations            create_deep_agent         evaluate()      Context Hub
   (tools, tiers, teams)    (data, not             + org middleware         thresholds      ledger
                             exceptions)           + interrupt_on           baseline         catalog
```

## Mapping to the LangChain stack

| Factory piece | Built on | Notes |
|---|---|---|
| `harness.build_agent` | `deepagents.create_deep_agent` | Model, tools, subagents, `interrupt_on`, filesystem mode from the spec. Checkpointer/store left to the platform in deployment. |
| `middleware.org_middleware` | `langchain.agents.middleware` | `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, plus two custom `AgentMiddleware` classes using `wrap_tool_call`: allowlist and audit. |
| Human-in-the-loop | Deep Agents `interrupt_on` → `HumanInTheLoopMiddleware` | Sensitive registry tools must be listed in `oversight.approve`; policy enforces it. Decisions resolved with `Command(resume=...)`, the Agent Inbox, or the SDK. |
| Filesystem modes | `FilesystemMiddleware(tools=[...])` name-matched override | `scratch` (default), `read_only` (engineering), `none` (support: no file tools beyond the required `read_file`). |
| Subagents | Deep Agents `SubAgent` dicts | Each subagent gets its own org middleware stack and only the tools its spec lists. |
| Eval gate | `langsmith.evaluate`, `Client.create_dataset/create_examples` | Same evaluators offline and online. Online syncs `evals/dataset.jsonl` to a LangSmith dataset and uploads the experiment. |
| Promotion | `Client.push_agent` (Context Hub) | Pushes `AGENTS.md`, `agent.yaml`, baseline as the context bundle. Environment label moved in the Hub UI. |
| Feedback loop | `Client.list_runs` with filters | Errored and low-feedback root runs become pending cases. |
| Surfaces | Agent Server (`langgraph dev` / LangSmith Deployment) | `/mcp` for IDEs, `http.app` mount for the webhook, `crons.create` for schedules, Slack Bolt + SDK for Slack. |

## The spec

`agents/<name>/agent.yaml` is the whole interface for a builder:

```yaml
name: support_triage
team: support            # must exist in registry/teams.yaml
owner: support-lead@...  # accountable human
model_tier: standard     # a tier, never a model id
tools: [lookup_ticket, ..., issue_refund]   # all must be registered and allowed for the team
oversight:
  approve: [issue_refund]                   # required for any sensitive tool
limits: {max_model_calls: 10, max_tool_calls: 12, max_tool_calls_per_tool: 3}
surfaces:
  - {kind: webhook, target: /webhooks/helpdesk, input_template: {question: "Triage ticket {ticket_id}"}}
  - {kind: chat}
filesystem: none
evals:
  thresholds: [{evaluator: tool_usage, min_score: 0.9}, {evaluator: oversight, min_score: 1.0}, ...]
```

## The policy rules

| Rule | Question it answers |
|---|---|
| `team.exists` | Who owns this? |
| `model.exists`, `model.allowed` | Is this team allowed to spend at this tier? |
| `tool.exists`, `tool.allowed` | Is this tool approved, and for this team? |
| `oversight.sensitive` | Does every money-moving or externally-visible action pause for a human? |
| `oversight.unknown` | Is the approval list honest (only tools the agent has)? |
| `surface.identity` | Can a tool that acts *as a person* be reached from a surface with no person behind it? (No.) |
| `evals.required`, `evals.dataset` | Can this agent prove it works? |
| `instructions.exists` | Is there an `AGENTS.md`? |
| `surface.high_risk` (warning) | Is a high-risk tool reachable unattended? Allowed with approval, but flagged. |
| `surfaces.none` (warning) | Is the agent actually embedded anywhere? |

## The evaluators

Every agent is scored on four code evaluators; an LLM judge is opt-in per spec and only runs with a live model.

| Evaluator | Scores | Why it matters |
|---|---|---|
| `tool_usage` | expected tools called, forbidden tools not called | The agent did the work and did not do forbidden work |
| `oversight` | sensitive action paused exactly when the example says it should | Governance is tested, not assumed |
| `policy_compliance` | no `BLOCKED_BY_POLICY` tool results | The agent never reached for a tool it does not have |
| `answer_contains` | required phrases present in the final answer | Cheap proxy for correctness that catches regressions |
| `llm_judge` (optional) | reference-based 0..1 | Quality beyond phrase matching |

Thresholds are per agent. The gate also fails on regression against `evals/baseline.json`, which is rewritten only by a passing production promotion. Size `regression_tolerance` to the dataset: with four examples one partial miss moves a mean by 0.05, so the shipped agents use 0.1. A forty-example dataset can afford 0.02.

## Offline mode

`models.ScriptedChatModel` replays the `offline_trajectory` recorded next to each eval example, choosing the script by the user's request and advancing by the number of AI messages already in the thread. That makes it stateless and correct across human-in-the-loop resumes. The point is not to fake quality; it is to make the *pipeline* (policy, middleware, approvals, gate, promotion, surfaces) run in CI and in demos without any secret. Every report states its mode. The same evaluators run against the real model when a key is present.

## Surfaces and identity

| Surface | Identity | Mechanism |
|---|---|---|
| webhook, cron | service (unattended) | Agent Server `http.app` mount; `crons.create` |
| slack | user via bot identity | Slack Bolt app forwarding mentions to the assistant, threads keyed by Slack thread |
| mcp | user (the engineer's IDE) | Agent Server `/mcp` (Streamable HTTP, stateless; description from `langgraph.json`) |
| chat, sdk | user | Any LangGraph-compatible UI or the SDK |

Policy enforces the one hard rule: a `scope: user` tool cannot be reached from a service surface.

## The console

`surfaces/console.py` mounts a small API and a single HTML page into the same FastAPI app the webhook uses, so it ships inside the Agent Server. State comes from three places: the catalog builder (specs, policy, ledger, latest reports), the Agent Server through the async SDK (threads with `status="interrupted"` for approvals, recent threads for activity), and the environment (mode, LangSmith). Approve and reject create a run with `command={"resume": {"decisions": [...]}}`, one decision per pending action, which is the same resume the CLI and tests use. Gate and promote run the existing functions in a worker thread. Disk reads happen in threads too, because the Agent Server refuses blocking calls on its event loop.

## What is deliberately not here

Infrastructure (Kubernetes, self-hosted LangSmith), fine-tuning, and a custom UI. See [tradeoffs-and-limits.md](tradeoffs-and-limits.md).
