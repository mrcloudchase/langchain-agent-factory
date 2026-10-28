# Architecture

## One sentence

The organization defines what an agent is and how it reaches production; teams create agents from those definitions in a console; the factory generates the spec, enforces policy, builds the agent on LangChain's stack, gates promotion through the named process, opens surfaces, and keeps the catalog.

## Objects

| Object | Where | Owner |
|---|---|---|
| Archetype (`agent`, `workflow`) | code: `build/agent_harness.py`, `build/workflow_compiler.py` | platform |
| Template | `org/templates/<key>/` (template.yaml, steps.yaml, instructions.md, examples.jsonl) | platform or a team lead |
| Tool catalog | `org/tools/catalog.yaml`, implementations in `src/factory/tools/` | engineering |
| Process | `org/processes/<name>.yaml` | platform |
| Teams, users, model tiers, policy settings | `org/teams.yaml`, `org/models.yaml`, `org/policy.yaml` | platform |
| Instance | `agents/<name>/instance.yaml` plus `evals/` | a team |
| Generated spec | `agents/<name>/spec.generated.yaml` | the factory, never edited by hand |

## Flow

```
instance.yaml + template  ──materialize──►  AgentSpec  ──check_spec──►  violations (data)
                                                │
                                   build(spec)  ├── archetype=agent    ──► create_deep_agent + org middleware
                                                └── archetype=workflow ──► StateGraph of steps, each a bounded create_agent
                                                │
                                   run_gate(spec) ──► langsmith.evaluate over evals/dataset.jsonl (offline or uploaded)
                                                │
                       request_promotion(spec) ──► process transition: policy, evals, budget, then human gates ──► ledger
                                                │
                                   surfaces ──► Agent Server: factory graph, /mcp, webhook app, crons, Slack bot
```

## Mapping to the LangChain stack

| Factory piece | Built on |
|---|---|
| Agent archetype | `deepagents.create_deep_agent` with `interrupt_on`, `FilesystemMiddleware` modes, subagents with their own middleware |
| Workflow archetype | `langgraph.StateGraph`; each step is a `langchain.agents.create_agent` bounded to the step's tools, with `HumanInTheLoopMiddleware` on sensitive ones. Interrupts propagate from the step to the outer graph |
| Org middleware | `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, and two custom `AgentMiddleware` hooks (allowlist, audit) |
| Model tiers | `init_chat_model` with pinned params; the LLM Gateway is the production form |
| Eval gate | `langsmith.evaluate`, `Client.create_dataset`/`create_examples`/`update_examples`; experiments uploaded when a key exists |
| Promotion | process YAML drives gates; `Client.push_agent` pushes the context bundle to Context Hub on each stage |
| Serving | one `factory` graph in `langgraph.json`; each instance is an assistant with `configurable.agent`; created at runtime, no restart |
| Surfaces | Agent Server REST and `/mcp`, `http.app` mount for the webhook and console, `crons.create`, Slack Bolt |
| Console | FastAPI router plus one static page inside the Agent Server app; async SDK client; disk and model work in threads |
| Roles | `X-Factory-User` resolved against `org/teams.yaml`; stand-in for the Agent Server auth block |

## Policy rules

team.exists, template.allowed, process.exists, model.exists, model.allowed, tool.exists, tool.allowed, tool.template, oversight.sensitive, oversight.required, oversight.unknown, surface.identity, surface.template, surface.high_risk (warning), surfaces.none (warning), limits.ceiling, parameters.required, evals.required, evals.dataset, workflow.steps, instructions.exists. Severities and ceilings come from `org/policy.yaml`.

## Evaluators

`tool_usage`, `oversight`, `policy_compliance`, `answer_contains`, and an optional reference-based `llm_judge`. Thresholds live in the template. Baselines are written by a passing production promotion. Size `regression_tolerance` to the dataset.

## Offline mode

Every template ships trajectories next to its examples. Agent examples carry a flat script keyed by the request; workflow examples carry a script per step, found through a marker line each step prompt starts with. The scripted model is stateless and resumes correctly after an approval. This makes policy, build, gates, promotion, and the console work in CI and demos without any secret. Reports always state their mode.
