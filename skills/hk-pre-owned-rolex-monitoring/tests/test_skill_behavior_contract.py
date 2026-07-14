from __future__ import annotations

from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]


def test_skill_behavior_scenarios_are_explicit_and_routable() -> None:
    cases = yaml.safe_load(
        (SKILL_ROOT / "tests/fixtures/skill-behavior-cases.yaml").read_text(encoding="utf-8")
    )
    assert len(cases["should_trigger"]) >= 4
    assert len(cases["should_not_trigger"]) >= 3
    assert all(case.get("workflow") for case in cases["should_trigger"])
    assert all(case.get("reason") for case in cases["should_not_trigger"])


def test_description_targets_the_model_and_excludes_generic_inventory() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill.split("---", 2)[1]
    assert "Oriental Watch Hong Kong" in frontmatter
    assert "yesterday or a prior run" in frontmatter
    assert "generic inventory websites" in frontmatter
    assert "investment advice" in frontmatter
