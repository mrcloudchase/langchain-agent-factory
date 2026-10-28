# Tradeoffs and limits

## Chosen tradeoffs

- **Specs are generated, never written.** Builders fill parameters; the template owns structure. This is what makes a non-technical creator safe, and it means a team that needs something the template does not offer asks the platform team for a template change rather than editing YAML.
- **Workflows over agents for anything with side effects.** The claims template is a workflow so the only tool with side effects runs in one named step with one approval. Agents are reserved for open-ended tasks.
- **Process as data, roles as data.** Gates and approvers come from YAML; the console draws them. Roles are resolved from a header for the demo and would come from the Agent Server auth block in production.
- **Files, not a database.** Instances, the ledger, and reports are files under the repo. Honest for a demo, and reviewable; a real deployment would put instances and the ledger in a database and specs in Context Hub.
- **Code evaluators first.** Four deterministic evaluators every agent passes; an LLM judge is opt-in. Cheap, reproducible, and they catch the governance failures that matter most.

## Known limits

- The console's roles trust a header. Production means SSO on the Agent Server and the same checks.
- Context Hub environment labels are moved in the Hub UI; the SDK pushes commits.
- Model tiers are a local stand-in for the LLM Gateway; the harvest loop is a manual stand-in for Engine.
- Simulated integrations: helpdesk, CI, Slack posting, and claim recording are deterministic stand-ins. Repo reads are real.
- Templates are files; there is no template editor in the console.
- Hosted deployment persists nothing new across revisions, so a created agent would also need its spec pushed to Context Hub and pulled by the factory graph.
- Datasets are small. Four examples per template proves the gate works, not that an agent is good.

## What the first live run taught us (v1)

The offline gate passed every agent; the first live run with a real model failed all three, and each failure was real: a fixture the model distrusted, instructions that let the model ask for permission instead of calling the gated tool, and nondeterminism at the default temperature. Every fix was a fixture, an instruction, or a registry entry. The harness did not change. v2 keeps that discipline: parameters and templates are where iteration happens.
