# Demo script

A talk track for the recorded walkthrough (`demo/walkthrough.mp4`) and the terminal recording (`demo/platform.svg`). About six minutes spoken.

## Opening (30 seconds)

"Most companies I talk to have a few agents built three different ways. Leadership can't say what runs, who owns it, or how anyone knows it works, and every new agent waits on the one team that knows how to build them. LangChain gives you everything to build, evaluate and deploy one agent. What's left is the organizational layer: rules, a path to production, and a way for every team to build on it. That's what a Professional Services engagement should leave behind, and this is a working version of it. It's an independent demo; the company is fictional."

## Act 1: the platform team sets the rules (terminal, then Organization page)

- Show `org/`: teams and roles, model tiers, the tool catalog, two processes, three templates.
- "A template is the org's definition of a kind of agent: which tools, which actions always pause for a person, call limits, what it must pass, and which path to production. The support template is regulated because it moves money."
- Show `factory check` passing, then failing on a pull request that drops the refund approval. "The platform team changes rules by pull request. CI refuses one that would let an agent refund without a person."
- In the console, Organization shows the same thing read-only. "No template editor on purpose: the rules live in code review."

## Act 2: teams build their own agents (Create, Try it)

- As Dev on support: pick the customer support template, name it, set the refund policy, Review. "Policy runs before anything is written, and the review draws the path this agent will take."
- Try "Triage ticket T-1001": the agent reads the ticket, customer, order and policy, then pauses on `issue_refund`. Approve. "That pause isn't a prompt instruction. It's in the template, and Dev can't remove it."
- As Kai on engineering: the coding agent explains why PR 42 fails, from the failing test and the diff.
- As Noor on research: the research workflow plans, gathers from live sources (papers, Hacker News, PyPI releases) and writes a cited brief, including where the evidence is thin.
- As Rae: try the support template. Refused: not offered to research, tools not allowed for the team.

## Act 3: the gate (Evals, Configure, Promote)

- Run the gate: four evaluators, thresholds from the template, a link to the LangSmith experiment. Promote to staging.
- Change the refund policy to "escalate every refund to tier 2" and promote. Blocked: the agent stopped refunding a duplicate charge the org expects it to refund. "The builder had a reasonable idea. The gate shows what it would have broken, before a customer sees it."
- Revert and promote: checks pass, and the request waits for people.

## Act 4: approvals (Approvals inbox)

- As Sam, support lead: the request with its evidence. Approve.
- As Priya, platform: approve. Production saves the gate scores as the baseline and pushes a Context Hub version. History links both.
- "Nobody approves their own request, and one person can't satisfy two approvals."
- The coding agent and research workflow go through the standard process with Eli and Rae.

## Act 5: production teaches the gate (Try it, Evals)

- As Rae: ask the research workflow what LangGraph and Deep Agents shipped. Flag the answer: "It should name the exact versions and link the PyPI release pages." The flag is LangSmith feedback on that run.
- As Noor: the flag waits under Evals. Write what a correct answer must contain and add it. "Every future promotion runs this case."

## Close (30 seconds)

- As Chris, CTO: the catalog shows every agent, its team and owner, its stage and its last gate.
- "The platform team owns three templates and two processes. Every other team ships its own agents on them, and the org can still say what runs, who approved it, and how it's tested. That's how adoption grows past the first team."
