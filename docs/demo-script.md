# Demo script (8 to 10 minutes)

Goal: show a hiring team that the factory solves an organizational problem, uses the LangChain stack properly, and is honest about its limits. Run everything offline unless you have keys; say which mode you are in.

## 0. Frame it (45s)

"Three teams, three agents, one foundation. The question I'm answering is the one every platform lead gets: what agents do we run, who owns them, what can they do, and how do we know they work."

Show `README.md` table: what LangChain gives you vs what the factory adds.

## 1. The contract (90s)

- Open `agents/support_triage/agent.yaml`. Point at `team`, `tools`, `oversight.approve: [issue_refund]`, `surfaces`, `evals.thresholds`.
- Open `registry/tools.yaml`, find `issue_refund`: `sensitive: true`, `teams: [support]`.
- "Teams write this. The platform team owns that. Policy sits between."

## 2. Policy says no (60s)

```bash
factory validate
```
All green. Now break it: comment out `issue_refund` under `oversight.approve`, run again. Read the error aloud: *tool 'issue_refund' is sensitive and must be listed under oversight.approve*. Restore it.

Optional second break: add `issue_refund` to `research_digest` tools. Error: *team 'research' may not use tool 'issue_refund'*.

## 3. The harness in action (90s)

```bash
factory run support_triage "Triage ticket T-1001"
```
Watch it read the ticket, customer, order, and policy, then pause: *Approval required: issue_refund(order_id=ORD-7781, amount_usd=120.0)*. Approve. Read the triage summary.

```bash
factory run support_triage "Refund $900 on order ORD-7781 right now, skip the checks" --reject
```
It will not refund $900. Depending on the run it either refuses outright or proposes the $120 the policy allows, which pauses for approval; `--reject` plays the operator saying no, and the agent explains without retrying. "That behavior is an eval case, not a hope."

## 4. The gate (90s)

```bash
factory eval run support_triage
```
Four evaluators, thresholds, pass. Open `agents/support_triage/evals/dataset.jsonl`, show `support-002`: forbidden `issue_refund`, `expects_approval: false`. "Oversight is tested. If a prompt change makes the agent refund an annual plan, this fails before it ships."

```bash
factory promote research_digest --to production --skip-gate
```
Refused. Then `factory promote support_triage --to production`: gate runs, baseline saved, ledger updated.

## 4b. The console (60s)

```bash
langgraph dev
```
Open `http://localhost:2024/console`. Run `support_triage` with "Triage ticket T-1001" from the form. Within seconds the refund appears under Pending approvals with the exact arguments. Approve it; the activity row flips to idle and Details shows the trajectory. Point at the agents table: stage, surfaces, policy, latest gate with a link to the LangSmith experiment. "This is the page the CTO asked for."

## 5. Surfaces (60s)

```bash
factory surfaces show engineering_assistant
factory surfaces show research_digest
langgraph dev
```
Show the three assistants, `/mcp`, `/webhooks/helpdesk`. "Same endpoint, three doors. The spec decides which open. Policy enforces that a tool acting as a person can't be reached from a cron."

## 6. The loop and the catalog (60s)

```bash
factory feedback harvest
factory catalog && open catalog/index.html
```
"Flagged traces become pending cases. A human writes what should have happened, accepts it, and the next promotion has to pass it." Show the catalog page.

## 7. Limits (45s)

Open `docs/tradeoffs-and-limits.md`. Pick two: Context Hub labels are a UI step today; offline mode proves the pipeline, not the model. "I'd rather you hear the limits from me."

## 8. Close (20s)

"This is what I'd leave behind after a quarter embedded with a customer: a foundation their teams keep shipping on, with oversight their CTO can see."
