"""Create an agent instance from a template. The only way agents come into existence."""

from __future__ import annotations

import json
import shutil
from typing import Any

from factory.core.instance import Instance, SurfaceDecl, write_dataset
from factory.core.policy import PolicyResult, check_spec
from factory.core.spec import AgentSpec, materialize, write_generated
from factory.core.template import load_template


def example_row(
    name: str,
    idx: int,
    question: str,
    must_contain: list[str],
    reference: str = "",
    step_keys: list[str] | None = None,
) -> dict[str, Any]:
    answer = reference or " ".join(must_contain)
    # Workflow templates replay per step offline; every step answers the reference.
    trajectory: Any = (
        {"steps": {k: [{"answer": answer}] for k in step_keys}}
        if step_keys
        else [{"answer": answer}]
    )
    return {
        "id": f"{name}-u{idx:03d}",
        "inputs": {"question": question},
        "outputs": {
            "expected_tools": [],
            "forbidden_tools": [],
            "must_contain": must_contain,
            "expects_approval": None,
            "reference": answer,
        },
        "offline_trajectory": trajectory,
        "metadata": {"split": "user"},
    }


def draft_instance(**fields: Any) -> Instance:
    t = load_template(fields["template"])
    params = {**t.default_parameters(), **(fields.get("parameters") or {})}
    surfaces = fields.get("surfaces")
    if surfaces is not None:
        surfaces = [SurfaceDecl.model_validate(s) if isinstance(s, dict) else s for s in surfaces]
    return Instance(
        name=fields["name"],
        display_name=fields.get("display_name") or fields["name"].replace("_", " ").title(),
        template=t.key,
        team=fields.get("team") or t.team_default,
        owner=fields["owner"],
        purpose=fields.get("purpose") or t.summary,
        parameters=params,
        tools=fields.get("tools"),
        approve=fields.get("approve"),
        surfaces=surfaces,
        model_tier=fields.get("model_tier"),
        created_by=fields.get("created_by"),
    )


def validate_draft(
    **fields: Any,
) -> tuple[Instance | None, AgentSpec | None, PolicyResult | list[str]]:
    """Policy on a draft without writing anything."""
    try:
        inst = draft_instance(**fields)
        spec = materialize(inst)
    except Exception as e:  # noqa: BLE001
        return None, None, [str(e)]
    return inst, spec, check_spec(spec, require_files=False)


def create_instance(
    *, user_examples: list[dict[str, Any]] | None = None, force: bool = False, **fields: Any
) -> tuple[Instance, AgentSpec, PolicyResult]:
    inst = draft_instance(**fields)
    if inst.directory.exists() and not force:
        raise FileExistsError(f"agent '{inst.name}' already exists")
    t = load_template(inst.template)
    rows = [json.loads(json.dumps(e)) for e in t.examples]
    for i, ex in enumerate(user_examples or [], start=1):
        if ex.get("question"):
            rows.append(
                example_row(
                    inst.name,
                    i,
                    ex["question"],
                    ex.get("must_contain") or [],
                    ex.get("reference", ""),
                    step_keys=[s.key for s in t.steps] or None,
                )
            )
    spec = materialize(inst, t)
    inst.save()
    write_dataset(inst, rows)
    write_generated(spec)
    policy = check_spec(spec, template=t)
    if not policy.ok and not force:
        shutil.rmtree(inst.directory, ignore_errors=True)
    return inst, spec, policy


def regenerate(inst: Instance) -> AgentSpec:
    spec = materialize(inst)
    write_generated(spec)
    return spec
