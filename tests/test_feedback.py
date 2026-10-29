import pytest
from conftest import person

from factory.agents import store
from factory.lifecycle import feedback


def test_flagged_answer_becomes_a_live_eval_case(radar):
    case = feedback.flag(radar.name, person("rae"), "What shipped?", "Nothing.", "no versions")
    assert store().pending(radar.name)[0]["id"] == case["id"]

    with pytest.raises(PermissionError):
        feedback.accept(radar.name, case["id"], ["pypi.org"], person("dev"))
    feedback.accept(radar.name, case["id"], ["pypi.org"], person("noor"))

    row = store().dataset(radar.name)[-1]
    assert (
        row["outputs"] == {"must_contain": ["pypi.org"]} and row["metadata"]["split"] == "flagged"
    )
    assert store().pending(radar.name) == []


def test_accepting_needs_an_expectation(radar):
    case = feedback.flag(radar.name, person("rae"), "What shipped?", "Nothing.")
    with pytest.raises(ValueError):
        feedback.accept(radar.name, case["id"], [], person("noor"))
