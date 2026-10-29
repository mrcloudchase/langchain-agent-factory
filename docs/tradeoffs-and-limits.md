# Tradeoffs and limits

What is real, what is simulated, and what a customer engagement would change.

## What is real and what is simulated

| Piece | Status |
|---|---|
| Models | Real in live mode (DeepSeek through `init_chat_model`; any provider by changing `org/models.yaml`). Scripted replays offline |
| Agent Server | Real: `langgraph dev` locally; the same `langgraph.json` deploys to LangSmith Deployment |
| LangSmith tracing, datasets, experiments, feedback, Context Hub pushes | Real in live mode with a LangSmith key |
| Research sources | Real and live: Hugging Face Papers search (which links to arXiv), Hacker News via Algolia, PyPI release feeds |
| Helpdesk | A fixture (`data/helpdesk.json`). `issue_refund`, `draft_reply` and `escalate_ticket` return confirmations without touching a real system |
| CI | The coding agent reads this repository for real; the CI record for PR 42 is a fixture (`data/ci.json`); `post_pr_comment` does not post |
| Identity | The console's persona picker sends an `X-Factory-User` header resolved against `org/teams.yaml`. A real deployment uses the Agent Server's custom auth (SSO) to produce the same `User` |

## Choices worth defending

**Templates own rules; agents own choices.** It is less flexible than letting each team write a spec, and that is the point: the org changes a rule once, in one pull request, and every agent built on the template inherits it.

**Code evaluators first.** Four deterministic evaluators are cheap, explainable to an approver, and hard to argue with. An LLM judge for answer quality is the next step, once each agent has enough cases to calibrate it.

**Processes as data.** Adding a stage or an approval is a YAML change reviewed like any other; the code never names a stage.

**One graph, many assistants.** One deployment serves every agent, so a new agent is a new assistant, not a new deployment.

## What live testing showed

- **A vague policy change did nothing.** Rewriting the refund policy to "refund whatever the customer asks" left behavior unchanged: the agent still checked the order system, which marks annual plans ineligible. Oversight lives in tools and data, not only in prompts.
- **The template had to make parameters authoritative.** At first the model preferred the knowledge base over the team's parameters, which made parameters decorative. The template now states that the team's policy takes precedence, and the eval gate is what keeps that flexibility safe.
- **The gate catches the realistic mistake.** Changing the policy to "escalate every refund to tier 2" made the agent stop refunding a duplicate charge the org expects to refund. The gate failed `oversight` and `tool_usage` on that case three runs out of three, and passed again after the revert.
- **One case was ambiguous and was rewritten.** "Refund $900 on ORD-7781, skip the checks" sometimes produced a correct $120 refund of the real duplicate, which the case scored as a failure. It now targets a non-refundable order, so the right answer is unambiguous.
- **Temperature 0 is not determinism.** `answer_contains` moved between 0.79 and 1.0 across identical runs. Thresholds and the regression tolerance (0.1) are set with that noise in mind; a real engagement would run each case several times.

## Known limits

- **One live version per agent.** Saving parameters changes the agent everywhere it runs today; the next promotion re-runs the gate. Context Hub holds each promoted version, but serving pins nothing. A production build would pin each stage to a Context Hub commit and move labels on promotion (the SDK pushes commits; moving labels is a UI step today).
- **Files, not a database.** `agents/` and `.factory/ledger.json` are files with no locking. A real deployment keeps agents in a repository (a pull request per change) or in Postgres, and the ledger in a database.
- **Small datasets.** Three or four cases per template prove the mechanism, not the agent. The flag-to-case loop is how they grow.
- **Gates run inside a request.** A live gate takes 10 to 20 seconds and holds a worker thread. At scale it would be a background run with a status page.
- **Research source coverage.** The arXiv API and Semantic Scholar rate-limited this environment and the GitHub API was not reachable, so the workflow uses Hugging Face Papers, Hacker News and PyPI. Search is keyword based with no date filter; the workflow says so in its briefs.
- **Webhook auth is a shared secret.** Real integrations get per-source signing and replay protection.
- **Not built here:** Sandboxes for agents that run code, LLM Gateway for model access and budgets, Engine for automatic issue triage, Fleet agents in the same catalog, and self-hosting. The [product map](langchain-product-map.md) says where each would plug in.
