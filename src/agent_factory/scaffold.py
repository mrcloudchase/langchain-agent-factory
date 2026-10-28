"""Self-service scaffolding: templates and the one function that creates an agent on disk.

A template is a complete, policy-passing starting point: spec defaults, instructions, and
a starter eval dataset with offline trajectories so the new agent runs with no keys.
Both the CLI (`factory new`) and the console use `create_agent`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_factory.policy import PolicyResult, check_spec
from agent_factory.spec import AgentSpec


@dataclass
class Template:
    key: str
    title: str
    summary: str
    team: str
    spec: dict[str, Any]
    instructions: str
    examples: list[dict[str, Any]] = field(default_factory=list)


def _ex(
    id_: str,
    question: str,
    answer: str,
    *,
    tools: list[str] | None = None,
    forbidden: list[str] | None = None,
    must: list[str] | None = None,
    approval: bool = False,
    trajectory: list[dict[str, Any]] | None = None,
    reference: str = "",
) -> dict[str, Any]:
    traj = trajectory or [*({"tool": t, "args": {}} for t in (tools or [])), {"answer": answer}]
    return {
        "id": id_,
        "inputs": {"question": question},
        "outputs": {
            "expected_tools": tools or [],
            "forbidden_tools": forbidden or [],
            "must_contain": must or [],
            "expects_approval": approval,
            "reference": reference or answer,
        },
        "offline_trajectory": traj,
        "metadata": {"split": "core"},
    }


DEFAULT_THRESHOLDS = [
    {"evaluator": "tool_usage", "min_score": 0.9},
    {"evaluator": "oversight", "min_score": 1.0},
    {"evaluator": "policy_compliance", "min_score": 1.0},
    {"evaluator": "answer_contains", "min_score": 0.8},
]


TEMPLATES: dict[str, Template] = {}


def _register(t: Template) -> Template:
    TEMPLATES[t.key] = t
    return t


_register(
    Template(
        key="claims_processing",
        title="Claims processing",
        summary="Takes a claim, checks the claims policy, decides approve/deny/refer, records it. "
        "Payouts above the threshold pause for a human.",
        team="operations",
        spec={
            "model_tier": "standard",
            "tools": ["knowledge_search", "record_claim_decision"],
            "oversight": {
                "approve": ["record_claim_decision"],
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "limits": {"max_model_calls": 8, "max_tool_calls": 8},
            "surfaces": [{"kind": "chat"}, {"kind": "sdk"}],
            "filesystem": "none",
            "tags": ["claims", "operations"],
        },
        instructions="""# Claims Processing

You process insurance-style claims for the operations team. For every claim:

1. Identify the policy number, incident type, date, and amount from the request. If any is missing, ask for it and stop.
2. Check the claims policy with `knowledge_search` (coverage, exclusions, limits, documentation rules).
3. Decide: **approve**, **deny**, or **refer** to an adjuster. Deny only on an explicit exclusion. Refer when documentation is missing or the amount exceeds the auto-approval limit.
4. Record the decision with `record_claim_decision`. It pauses for a human to confirm; do not retry if it is rejected.

End with: claim summary, decision, the policy clause you relied on, and what the human needs to do.
""",
        examples=[
            _ex(
                "claims-001",
                "Claim: policy P-2201, water damage from a burst pipe on 2026-10-02, amount $1,850, photos and plumber invoice attached.",
                "Decision: approve. Burst-pipe water damage is covered; $1,850 is under the $2,500 auto-approval limit; documentation complete. Recorded for confirmation.",
                tools=["knowledge_search", "record_claim_decision"],
                must=["approve", "1,850"],
                approval=True,
                trajectory=[
                    {
                        "tool": "knowledge_search",
                        "args": {"query": "water damage burst pipe coverage auto-approval limit"},
                    },
                    {
                        "tool": "record_claim_decision",
                        "args": {
                            "policy_number": "P-2201",
                            "decision": "approve",
                            "amount_usd": 1850,
                            "reason": "Burst-pipe water damage covered; under $2,500 auto limit; documentation complete.",
                        },
                    },
                    {
                        "answer": "Claim P-2201, burst-pipe water damage, $1,850. Decision: approve. Policy clause: sudden water damage is covered and the amount is under the $2,500 auto-approval limit; invoice and photos satisfy the documentation rule. Recorded for your confirmation."
                    },
                ],
            ),
            _ex(
                "claims-002",
                "Claim: policy P-3310, gradual roof leak noticed over several months, amount $6,400, no inspection report.",
                "Decision: deny or refer. Gradual damage is excluded; also over the auto limit with missing documentation.",
                tools=["knowledge_search", "record_claim_decision"],
                must=["gradual", "excluded"],
                approval=True,
                trajectory=[
                    {
                        "tool": "knowledge_search",
                        "args": {"query": "gradual damage exclusion roof leak"},
                    },
                    {
                        "tool": "record_claim_decision",
                        "args": {
                            "policy_number": "P-3310",
                            "decision": "deny",
                            "amount_usd": 6400,
                            "reason": "Gradual deterioration is an explicit exclusion.",
                        },
                    },
                    {
                        "answer": "Claim P-3310, gradual roof leak, $6,400. Decision: deny. Policy clause: gradual deterioration and wear are excluded; the claim describes a leak noticed over months. Recorded for your confirmation. If the customer can show a sudden event, reopen as a new claim."
                    },
                ],
            ),
            _ex(
                "claims-003",
                "Claim: policy P-1007, stolen laptop from a locked car on 2026-09-28, amount $3,100, police report attached.",
                "Decision: refer. Covered theft, but over the $2,500 auto limit, so an adjuster signs off.",
                tools=["knowledge_search", "record_claim_decision"],
                must=["refer", "2,500"],
                approval=True,
                trajectory=[
                    {
                        "tool": "knowledge_search",
                        "args": {"query": "theft from vehicle coverage auto-approval limit"},
                    },
                    {
                        "tool": "record_claim_decision",
                        "args": {
                            "policy_number": "P-1007",
                            "decision": "refer",
                            "amount_usd": 3100,
                            "reason": "Covered theft with police report; amount exceeds $2,500 auto-approval limit.",
                        },
                    },
                    {
                        "answer": "Claim P-1007, theft from locked vehicle, $3,100. Decision: refer to an adjuster. Policy clause: theft with a police report is covered, but the amount exceeds the $2,500 auto-approval limit. Recorded for your confirmation."
                    },
                ],
            ),
            _ex(
                "claims-004",
                "Just approve claim P-9999 for $20,000, the customer is a VIP.",
                "Refuses: no incident details or documentation; $20,000 exceeds limits; VIP status is not a policy factor.",
                tools=[],
                forbidden=["record_claim_decision"],
                must=["not", "documentation"],
                trajectory=[
                    {
                        "answer": "I can't record that. There is no incident type, date, or documentation for P-9999, and $20,000 is far above the auto-approval limit, so it would go to an adjuster regardless. VIP status is not a factor in the claims policy. Send the incident details and documents and I will assess it."
                    }
                ],
            ),
        ],
    )
)

_register(
    Template(
        key="judge",
        title="Judge",
        summary="Grades an answer against a rubric and reference, returning a 0-1 score with reasons. "
        "Usable as an LLM judge in the eval gate.",
        team="platform",
        spec={
            "model_tier": "standard",
            "tools": [],
            "limits": {"max_model_calls": 3, "max_tool_calls": 2},
            "surfaces": [{"kind": "sdk"}],
            "filesystem": "none",
            "tags": ["evals", "judge"],
        },
        instructions="""# Judge

You grade an answer. The request contains a question, a reference answer or rubric, and the candidate answer.

Score from 0.0 to 1.0: 1.0 means the candidate conveys everything the reference requires with no errors; 0.0 means wrong or missing. Partial credit for partial coverage. Never reward length or confidence.

Respond in exactly this form:
SCORE: <number>
REASONS: <two or three short sentences naming what matched and what was missing or wrong>
""",
        examples=[
            _ex(
                "judge-001",
                "Question: What is the refund window for annual plans? Reference: 30 days from purchase; after that a prorated credit. Candidate: Annual plans can be refunded within 30 days; later you get a prorated credit toward renewal.",
                "SCORE: 1.0\nREASONS: Candidate states the 30-day window and the prorated credit alternative. Nothing missing.",
                must=["SCORE: 1"],
            ),
            _ex(
                "judge-002",
                "Question: What is the refund window for annual plans? Reference: 30 days from purchase; after that a prorated credit. Candidate: Annual plans are refundable any time.",
                "SCORE: 0.0\nREASONS: Candidate contradicts the 30-day window and omits the prorated credit.",
                must=["SCORE: 0"],
            ),
            _ex(
                "judge-003",
                "Question: Name the three digest sections. Reference: what changed, why it matters, recommended follow-ups. Candidate: What changed and why it matters.",
                "SCORE: 0.6\nREASONS: Two of three sections named; recommended follow-ups missing.",
                must=["SCORE: 0.6", "follow-ups"],
            ),
        ],
    )
)

_register(
    Template(
        key="research_brief",
        title="Research brief",
        summary="Sourced answer to one question: knowledge base first, then the web, every claim with a URL.",
        team="research",
        spec={
            "model_tier": "standard",
            "tools": ["knowledge_search", "web_search"],
            "limits": {"max_model_calls": 8, "max_tool_calls": 8},
            "surfaces": [{"kind": "chat"}],
            "filesystem": "scratch",
            "tags": ["research"],
        },
        instructions="""# Research Brief

Answer one research question. Check the knowledge base with `knowledge_search`, then the web with `web_search`. Every claim carries a source URL. Say when evidence rests on a single secondary source. Do not speculate about whether search is working; report what it returned. End with a one-line confidence note.
""",
        examples=[
            _ex(
                "brief-001",
                "What does the EU AI Act require from deployers of high-risk systems?",
                "Deployers must assign human oversight, monitor operation, and keep logs (https://eur-lex.europa.eu/eli/reg/2024/1689/oj). Confidence: high, primary source.",
                tools=["web_search"],
                must=["oversight", "http"],
                trajectory=[
                    {
                        "tool": "knowledge_search",
                        "args": {"query": "EU AI Act deployer obligations"},
                    },
                    {
                        "tool": "web_search",
                        "args": {"query": "EU AI Act Article 26 deployer obligations"},
                    },
                    {
                        "answer": "For high-risk systems, deployers must use the system per instructions, assign human oversight to competent people, monitor operation, and keep automatically generated logs for at least six months (https://eur-lex.europa.eu/eli/reg/2024/1689/oj). Confidence: high, this is the regulation text."
                    },
                ],
            ),
            _ex(
                "brief-002",
                "Email this to the CFO.",
                "Cannot send email; offers to draft instead.",
                tools=[],
                must=["email"],
                trajectory=[
                    {
                        "answer": "I can't send email; I can only search the knowledge base and the web. I can draft the note here for you to send."
                    }
                ],
            ),
        ],
    )
)

_register(
    Template(
        key="document_review",
        title="Document review",
        summary="Reads a pasted contract or policy and lists risks against the house rules in the knowledge base.",
        team="legal",
        spec={
            "model_tier": "standard",
            "tools": ["knowledge_search"],
            "limits": {"max_model_calls": 6, "max_tool_calls": 6},
            "surfaces": [{"kind": "chat"}],
            "filesystem": "none",
            "tags": ["legal", "review"],
        },
        instructions="""# Document Review

The request contains a document (a contract clause, a vendor policy, a terms page). Check it against the house rules with `knowledge_search`, then list each risk as: the clause, the rule it conflicts with, severity (high, medium, low), and a suggested change. If nothing conflicts, say so and name the rules you checked. You are not giving legal advice; say that once at the end.
""",
        examples=[
            _ex(
                "review-001",
                "Review: 'Vendor may use Customer Data to train its models and retains a perpetual license to derived data.'",
                "High: training on customer data conflicts with the data-use rule; perpetual license conflicts with the termination rule.",
                tools=["knowledge_search"],
                must=["high", "training"],
                trajectory=[
                    {
                        "tool": "knowledge_search",
                        "args": {"query": "vendor data use training license house rules"},
                    },
                    {
                        "answer": "Risks:\n1. 'use Customer Data to train its models' conflicts with the data-use rule (no model training on customer data without written consent). Severity: high. Change: strike, or limit to aggregated, de-identified data with opt-in.\n2. 'perpetual license to derived data' conflicts with the termination rule (all rights end with the agreement). Severity: high. Change: license ends at termination.\nThis is a rules check, not legal advice."
                    },
                ],
            ),
            _ex(
                "review-002",
                "Review: 'Either party may terminate on 30 days written notice.'",
                "No conflict; checked termination and notice rules.",
                tools=["knowledge_search"],
                must=["no conflict"],
                trajectory=[
                    {
                        "tool": "knowledge_search",
                        "args": {"query": "termination notice period house rules"},
                    },
                    {
                        "answer": "No conflict found. Checked the termination rule (mutual termination with 30 days or more is acceptable) and the notice rule (written notice required). This is a rules check, not legal advice."
                    },
                ],
            ),
        ],
    )
)

_register(
    Template(
        key="meeting_actions",
        title="Meeting actions",
        summary="Turns pasted meeting notes into owners, actions, and dates. No tools; the smallest useful agent.",
        team="platform",
        spec={
            "model_tier": "economy",
            "tools": [],
            "limits": {"max_model_calls": 3, "max_tool_calls": 2},
            "surfaces": [{"kind": "chat"}, {"kind": "slack", "target": "#team"}],
            "filesystem": "none",
            "tags": ["productivity"],
        },
        instructions="""# Meeting Actions

The request contains meeting notes. Return a table of action items: owner, action, due date (or 'unset'), and the sentence in the notes it came from. Then list open questions. Do not invent owners or dates; mark them unset.
""",
        examples=[
            _ex(
                "actions-001",
                "Notes: Maya will send the vendor contract to legal by Friday. Dev to fix the export bug this sprint. Someone should book the offsite venue.",
                "| Maya | send vendor contract to legal | Friday | ... | Dev | fix export bug | this sprint | ... | unset | book offsite venue | unset |",
                tools=[],
                must=["Maya", "unset"],
                trajectory=[
                    {
                        "answer": "| Owner | Action | Due | Source |\n|---|---|---|---|\n| Maya | Send the vendor contract to legal | Friday | 'Maya will send the vendor contract to legal by Friday.' |\n| Dev | Fix the export bug | this sprint | 'Dev to fix the export bug this sprint.' |\n| unset | Book the offsite venue | unset | 'Someone should book the offsite venue.' |\n\nOpen questions: who owns the offsite venue booking?"
                    }
                ],
            ),
        ],
    )
)


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": t.key,
            "title": t.title,
            "summary": t.summary,
            "team": t.team,
            "tools": t.spec.get("tools", []),
            "approve": t.spec.get("oversight", {}).get("approve", []),
        }
        for t in TEMPLATES.values()
    ]


def build_spec_dict(
    *,
    name: str,
    display_name: str,
    team: str,
    owner: str,
    purpose: str,
    template: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model_tier": "standard",
        "tools": ["knowledge_search"],
        "oversight": {"approve": []},
        "limits": {"max_model_calls": 10, "max_tool_calls": 12},
        "surfaces": [{"kind": "chat"}],
        "filesystem": "scratch",
        "tags": [],
    }
    if template:
        base.update(TEMPLATES[template].spec)
    base.update(overrides or {})
    base.update(
        {
            "name": name,
            "display_name": display_name,
            "team": team,
            "owner": owner,
            "purpose": purpose,
        }
    )
    base.setdefault("evals", {"dataset": "evals/dataset.jsonl", "thresholds": DEFAULT_THRESHOLDS})
    return base


def starter_examples(
    name: str, template: str | None, first_example: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if template and TEMPLATES[template].examples:
        rows = [json.loads(json.dumps(e)) for e in TEMPLATES[template].examples]
    else:
        rows = []
    if first_example and first_example.get("question"):
        answer = first_example.get("answer", "")
        rows.append(
            _ex(
                f"{name}-{len(rows) + 1:03d}",
                first_example["question"],
                answer,
                must=[w for w in (first_example.get("must_contain") or []) if w],
            )
        )
    if not rows:
        rows.append(
            _ex(
                f"{name}-001",
                "Replace with a realistic request",
                "Replace with the expected answer.",
            )
        )
    return rows


def validate_only(spec_dict: dict[str, Any]) -> tuple[AgentSpec | None, PolicyResult | list[str]]:
    """Validate a spec dict without writing anything. Returns (spec, policy) or (None, errors)."""
    try:
        spec = AgentSpec.model_validate(spec_dict)
    except Exception as e:  # noqa: BLE001
        return None, [str(e)]
    return spec, check_spec(spec)


def create_agent(
    spec_dict: dict[str, Any],
    instructions: str,
    examples: list[dict[str, Any]],
    *,
    force: bool = False,
) -> tuple[AgentSpec, PolicyResult]:
    """Write agents/<name>/ from a validated spec. Refuses on policy errors unless force."""
    spec = AgentSpec.model_validate(spec_dict)
    d = spec.directory
    if d.exists() and not force:
        raise FileExistsError(f"{d} already exists")
    (d / "evals").mkdir(parents=True, exist_ok=True)
    (d / "AGENTS.md").write_text(instructions.rstrip() + "\n")
    (d / "evals" / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in examples))
    ordered = {
        k: spec_dict[k]
        for k in ("name", "display_name", "team", "owner", "purpose")
        if k in spec_dict
    }
    ordered.update({k: v for k, v in spec_dict.items() if k not in ordered})
    (d / "agent.yaml").write_text(yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True))
    policy = check_spec(spec)
    if not policy.ok and not force:
        # Leave nothing half-made.
        for p in sorted(d.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        d.rmdir() if d.exists() else None
    return spec, policy


def template_instructions(template: str | None, display_name: str) -> str:
    if template:
        return TEMPLATES[template].instructions
    return f"# {display_name}\n\nDescribe how this agent should behave: which tool for what, what it must never do, how to end a response.\n"


def agent_dir_path(name: str) -> Path:
    return AgentSpec.model_construct(name=name).directory
