"""Offline historical comparisons; never execute live failure injections."""

import json
import runpy
from pathlib import Path

from lyme_gap_atlas_data.operation_capabilities import assess_operation, load_contract

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads(
    (ROOT / "tests/fixtures/delivery-regressions/expected-v1.json").read_text(encoding="utf-8-sig")
)


def test_engine_boundaries_remain_unknown_without_execution() -> None:
    report = assess_operation(load_contract(), operation="semantic_release", environment="prod")
    cases = {case["id"]: case for case in CORPUS["cases"]}
    for case_id in ("336", "353", "365", "stale-context"):
        assert report["status"] == cases[case_id]["expected"]
    assert report["mutation_started"] is False


def test_canonical_fixture_does_not_count_source_only_geography() -> None:
    case = next(case for case in CORPUS["cases"] if case["id"] == "365")
    canonical, source = set(case["canonical"]), set(case["source"])
    assert sorted(canonical & source) == case["matches"]
    assert sorted(canonical - source) == case["missing_unknown"]
    assert sorted(source - canonical) == case["source_only"]
    assert len(canonical & source) == 2
    assert len(canonical) == 3


def test_historical_denied_runtime_insert_matches_frozen_blocked_expectation() -> None:
    case = next(case for case in CORPUS["cases"] if case["id"] == "366")
    contract = load_contract()
    report = assess_operation(
        contract,
        operation="semantic_release",
        environment="prod",
        observed={"capabilities": {case["runtime_object"]: False}},
    )
    assert report["status"] == case["expected"]
    findings = {f["check"]: f["status"] for f in report["findings"]}
    assert findings[f"runtime_capability:{case['runtime_object']}"] == case["expected"]
    assert findings["effective_identity"] == "UNKNOWN"
    assert report["mutation_started"] is False
    assert (
        next(f for f in report["findings"] if f["check"] == "grant_authority")["status"]
        == case["grant_authority"]
    )


def test_missing_context_is_actionable(tmp_path: Path) -> None:
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    assert check["missing_context"](tmp_path, ("AGENTS.md",)) == ["AGENTS.md"]


def test_skills_resolve_required_reference_index() -> None:
    skills = list((ROOT / ".agents/skills").glob("*/SKILL.md"))
    assert len(skills) == 4
    for skill in skills:
        reference = skill.parent / "references/workflow.md"
        assert reference.is_file()
        for path in (
            "config/operation-capabilities-v1.yml",
            "docs/delivery/handoff-v1.schema.json",
            "docs/delivery/data374-recipes.md",
        ):
            assert (ROOT / path).is_file()
