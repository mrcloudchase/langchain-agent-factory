import shutil

import pytest
import yaml
from pydantic import ValidationError

from factory.org import load_org
from factory.templates import load_template


def test_shipped_org_is_consistent():
    org = load_org()
    assert org.problems() == []
    assert set(org.templates) == {"support_agent", "coding_agent", "ai_research"}


def test_problems_catch_cross_reference_errors(tmp_path, monkeypatch):
    shutil.copytree("org", tmp_path / "org")
    shutil.copytree("data", tmp_path / "data")
    path = tmp_path / "org/templates/coding_agent/template.yaml"
    template = yaml.safe_load(path.read_text())
    template["process"] = "fast_track"
    path.write_text(yaml.safe_dump(template))
    monkeypatch.setenv("FACTORY_ROOT", str(tmp_path))
    load_org.cache_clear()

    assert any("fast_track" in p for p in load_org().problems())


def test_template_cannot_require_approval_for_a_tool_it_lacks(tmp_path):
    shutil.copytree("org/templates/support_agent", tmp_path / "support_agent")
    path = tmp_path / "support_agent/template.yaml"
    template = yaml.safe_load(path.read_text())
    template["approvals"] = ["post_pr_comment"]
    path.write_text(yaml.safe_dump(template))

    with pytest.raises(ValidationError, match="approvals"):
        load_template(tmp_path / "support_agent")


def test_roles():
    org = load_org()
    dev, sam, priya = (org.user(f"{n}@halcyon.example") for n in ("dev", "sam", "priya"))
    assert dev.can_build_for("support") and not dev.can_build_for("engineering")
    assert sam.can_approve("team", "support") and not sam.can_approve("platform", "support")
    assert priya.can_approve("platform", "support") and priya.can_build_for("research")
    assert not dev.can_approve("team", "support")
