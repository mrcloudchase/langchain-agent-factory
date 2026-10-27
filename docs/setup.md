# Setup

## Local, offline (no keys)

```bash
uv venv && uv pip install -e ".[dev]"
factory validate && factory eval run && pytest
```

Offline mode is automatic when no provider key is present, or forced with `FACTORY_OFFLINE=1`. Every eval report and `factory run` says which mode it used.

## Live model

Set one provider key in `.env`:

```
ANTHROPIC_API_KEY=...        # default tiers in registry/models.yaml use Anthropic models
```

`registry/models.yaml` maps tiers to `provider:model` strings resolved with `init_chat_model`, so switching providers is a registry edit, not a code change.

## LangSmith

A LangSmith account on the Developer (free) plan provides everything the factory uses except hosted deployment:

```
LANGSMITH_API_KEY=...
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=agent-factory
```

With the key set:

- `factory eval run` syncs each agent's dataset to LangSmith (`<agent>-evals`) and uploads experiments. The report prints the experiment URL.
- `factory promote` pushes `AGENTS.md`, `agent.yaml`, and the baseline to Context Hub as the agent's context bundle. Moving the `staging` or `production` environment label to that commit is done in the Hub UI (the SDK does not expose it yet).
- `factory feedback harvest` pulls errored and low-feedback root runs for each agent from the project.

Plan notes as of October 2026: Developer includes 5k traces per month and a Fleet allowance. Hosted LangSmith Deployment and Engine are on Plus. Check [langchain.com/pricing](https://www.langchain.com/pricing).

## Serving

```bash
langgraph dev                        # http://localhost:2024, Studio link printed
factory surfaces show support_triage
```

`langgraph.json` registers the three agents and mounts the webhook FastAPI app. The Agent Server then provides:

- REST and streaming runs for each assistant (`support_triage`, `research_digest`, `engineering_assistant`)
- `/mcp`: each agent as an MCP tool (Streamable HTTP). `claude mcp add --transport http engineering_assistant http://localhost:2024/mcp`
- `/webhooks/helpdesk`: POST with `X-Factory-Secret` to trigger support triage
- cron: `factory surfaces register-crons research_digest`

Approvals raised by `interrupt_on` appear in LangSmith's Agent Inbox when traced, or can be resolved with the SDK (`Command(resume=...)`).

## Hosted deployment

Push the repository and create a deployment from it in LangSmith (Plus plan). Checkpointer and store are provisioned by the platform; the graphs in `src/agent_factory/graphs.py` deliberately pass none.
