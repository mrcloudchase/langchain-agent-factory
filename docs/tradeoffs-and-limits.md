# Tradeoffs and limits

Stated plainly, because a customer would ask and a reviewer should.

## Tradeoffs we chose

**The spec constrains builders on purpose.** A team cannot pick a model id, add an unregistered tool, or skip evals. That is the product. The escape hatch is a `CompiledSubAgent` or a raw LangGraph graph registered in `langgraph.json`, and the position we would hold with a customer is: fine, but it still goes through the gate and the catalog.

**Code evaluators first, LLM judge second.** The four code evaluators are deterministic, free, and run in CI without secrets. They catch the failures that matter most for governance (wrong tools, missing approvals, policy violations). They are a weak proxy for answer quality, which is why `llm_judge` exists and why the harvest loop feeds real failures back in.

**Approval is a pause, not a workflow.** `interrupt_on` stops the run and something has to resume it: the Agent Inbox, the SDK, or the CLI. We did not build an approval UI or routing (who approves what). For a real customer this is usually the first thing to extend, and Fleet's Agent Inbox is the natural place to point them.

**Offline mode is a replay, not a model.** It proves the pipeline, not the agent. Reports say which mode produced them so nobody confuses the two.

**One deployment, many graphs.** All three agents ship in one `langgraph.json`. Simple for a demo; a larger org would split by team to isolate blast radius and cost, and the factory's layout already supports one `langgraph.json` per team.

## Known limits

- **Context Hub environment labels.** The SDK pushes commits (`push_agent`) but does not move the `staging`/`production` labels; that step is in the Hub UI today. Promotion records the commit URL and says so.
- **MCP is stateless per request.** Multi-turn IDE sessions must carry thread context in the client. Fine for "explain this" and "why is CI red", awkward for long back-and-forth.
- **The allowlist runs after the model chose a tool.** It is defense in depth. The primary control is that the model only sees approved tools at build time. Deep Agents' built-in file and `task` tools are always allowed; `filesystem: none` reduces them to `read_file` (the minimum the middleware accepts).
- **Harvest filters are coarse.** Errored runs and low feedback scores. A real deployment would add online evaluator failures and sampling. LangSmith Engine does this clustering far better; the factory's loop is the manual version a team can run on day one.
- **Simulated integrations.** Helpdesk, CI, and messaging tools are small deterministic stand-ins. Repo reads are real. Swapping in Zendesk or GitHub is a registry entry plus a tool function; the policy and surfaces do not change.
- **No cost accounting beyond limits.** Budgets cap calls per run. Spend per team comes from LangSmith cost tracking by project/tag, which the catalog does not yet pull in.
- **No multi-tenant store isolation.** The spec has no namespace rules for long-term memory. A customer with per-user memory would add `StoreBackend` namespacing in the harness.

## What the first live run taught us

The offline gate passed on every agent. The first run against a real model (DeepSeek, via a registry edit) failed all three, and each failure was a real finding, not noise:

- The research agent noticed that the simulated search results pointed at `example.com`, concluded the backend was stubbed, and refused to post the digest. The fixture was wrong, and the agent was right to say so.
- The engineering agent asked for permission in prose instead of calling `post_pr_comment`, so the approval pause never fired. The instructions now say that the tool call *is* the permission step.
- The engineering agent read the real repository, saw the webhook fix already present on the branch, and refused to post a review claiming otherwise. The CI fixture now carries the PR's diff.
- A second research run failed on tool usage where the first had passed. Model tiers now carry pinned parameters, and the platform sets temperature to zero so gates are reproducible.

Every one of these is a change to a fixture, an instruction file, or the registry. None touched the harness. That is the division of responsibility working as intended, and it is the kind of iteration a customer's teams would do weekly.

## What we would do next with a customer

1. Approval routing: map `oversight.approve` tools to approver groups and surface them in the Agent Inbox or Slack.
2. Live gate on PRs with a small LangSmith dataset per agent, plus an LLM judge with a rubric the team wrote.
3. Online evaluators and Engine for issue clustering; keep the harvest loop as the curated path into the gate.
4. Split deployments by team; add LangSmith cost tracking by tag to the catalog.
5. A second provider in `models.yaml` with `ModelFallbackMiddleware` wired from the tier's `fallback`.
