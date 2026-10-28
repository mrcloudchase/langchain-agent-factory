"""Self-service scaffolding: templates pass policy and run offline; refusals leave no files."""

import pytest

from agent_factory.evals import run_gate
from agent_factory.scaffold import (
    TEMPLATES,
    build_spec_dict,
    create_agent,
    starter_examples,
    template_instructions,
    validate_only,
)


@pytest.fixture
def agents_tmp(tmp_path, monkeypatch):
    """Redirect agents/ to a temp dir so created agents never touch the repo."""
    import agent_factory.paths as paths

    monkeypatch.setattr(paths, "AGENTS_DIR", tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    return tmp_path / "agents"


@pytest.mark.parametrize("key", sorted(TEMPLATES))
def test_every_template_creates_and_passes_gate_offline(agents_tmp, key):
    t = TEMPLATES[key]
    sd = build_spec_dict(
        name=f"t_{key}",
        display_name=t.title,
        team=t.team,
        owner="x@halcyon.example",
        purpose=t.summary,
        template=key,
    )
    spec, policy = create_agent(
        sd, template_instructions(key, t.title), starter_examples(f"t_{key}", key, None)
    )
    assert policy.ok, [v.message for v in policy.errors]
    assert (spec.directory / "agent.yaml").exists() and spec.instructions_path.exists()
    report = run_gate(spec)
    assert report.passed, report.failures


def test_policy_refusal_writes_nothing(agents_tmp):
    sd = build_spec_dict(
        name="bad_claims",
        display_name="Bad",
        team="research",
        owner="x@halcyon.example",
        purpose="A research agent that tries to record claims.",
        template="claims_processing",
    )
    spec, policy = create_agent(
        sd, "# x", starter_examples("bad_claims", "claims_processing", None)
    )
    assert not policy.ok and "tool.allowed" in {v.rule for v in policy.errors}
    assert not (agents_tmp / "bad_claims").exists()


def test_duplicate_name_is_refused(agents_tmp):
    sd = build_spec_dict(
        name="dup",
        display_name="Dup",
        team="platform",
        owner="x@y",
        purpose="Meeting actions for the platform team, twice.",
        template="meeting_actions",
    )
    create_agent(sd, "# dup", starter_examples("dup", "meeting_actions", None))
    with pytest.raises(FileExistsError):
        create_agent(sd, "# dup", starter_examples("dup", "meeting_actions", None))


def test_first_example_becomes_a_runnable_case(agents_tmp):
    sd = build_spec_dict(
        name="notes_bot",
        display_name="Notes Bot",
        team="platform",
        owner="x@y",
        purpose="Turns notes into actions for the platform team.",
        template="meeting_actions",
    )
    rows = starter_examples(
        "notes_bot",
        "meeting_actions",
        {
            "question": "Notes: Sam ships v2 Monday.",
            "answer": "Sam v2 Monday",
            "must_contain": ["Sam", "Monday"],
        },
    )
    assert rows[-1]["inputs"]["question"] == "Notes: Sam ships v2 Monday."
    assert rows[-1]["outputs"]["must_contain"] == ["Sam", "Monday"]
    spec, policy = create_agent(sd, template_instructions("meeting_actions", "Notes Bot"), rows)
    assert policy.ok and run_gate(spec).passed


def test_validate_only_reports_spec_errors_without_writing(agents_tmp):
    spec, result = validate_only(
        {"name": "Bad Name", "display_name": "x", "team": "platform", "owner": "o", "purpose": "p"}
    )
    assert spec is None and result
    assert not list(agents_tmp.iterdir())
