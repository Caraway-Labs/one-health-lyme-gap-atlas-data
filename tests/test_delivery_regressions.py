"""Offline historical comparisons; never execute live failure injections."""

import json
import runpy
from pathlib import Path

import pytest

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
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    assert check["skill_reference_errors"](ROOT) == []


@pytest.mark.parametrize(
    "reference",
    [
        "docs/missing.md",
        "../outside.md",
        "/outside.md",
        "C:/outside.md",
        "https://example.test/file.md",
        "docs/file.md#fragment",
        "docs//file.md",
        "docs/./file.md",
        "docs/file.md?query",
        "docs\\file.md",
    ],
)
def test_declared_skill_references_reject_missing_or_unsafe_paths(tmp_path: Path, reference: str):
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    skill = tmp_path / ".agents/skills/example"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("[index](references/workflow.md)", encoding="utf-8")
    (skill / "references/workflow.md").write_text(f"- `{reference}`\n", encoding="utf-8")
    errors = check["skill_reference_errors"](tmp_path)
    assert len(errors) == 1
    assert "index line 1" in errors[0]


@pytest.mark.parametrize("declaration", ["- docs/file.md", "- `docs/file.md", ""])
def test_skill_reference_indexes_reject_malformed_or_empty_declarations(tmp_path, declaration):
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    skill = tmp_path / ".agents/skills/example"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("[index](references/workflow.md)", encoding="utf-8")
    (skill / "references/workflow.md").write_text(declaration, encoding="utf-8")
    assert check["skill_reference_errors"](tmp_path)


def test_skill_entrypoint_rejects_missing_index_and_unsupported_links(tmp_path):
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    skill = tmp_path / ".agents/skills/example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("[index](../other/index.md)", encoding="utf-8")
    errors = check["skill_reference_errors"](tmp_path)
    assert any("missing declared reference index" in error for error in errors)
    assert any("unsupported or malformed reference" in error for error in errors)


def test_existing_declared_paths_resolve_files_and_directories(tmp_path):
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    (tmp_path / "docs").mkdir()
    path = tmp_path / "docs/reference.md"
    path.write_text("reference", encoding="utf-8")
    assert check["resolve_reference"](tmp_path, tmp_path, "docs/reference.md") == path
    assert check["resolve_reference"](tmp_path, tmp_path, "docs/") == tmp_path / "docs"


def test_reference_symlink_cannot_escape_repository(tmp_path):
    check = runpy.run_path(str(ROOT / "scripts/check_agent_context.py"))
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "link.md").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable; hosted Linux CI exercises this check")
    with pytest.raises(ValueError, match="escapes repository"):
        check["resolve_reference"](root, root, "link.md")
