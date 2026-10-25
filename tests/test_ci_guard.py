"""The sourced CI guard helper reports failures and preserves shell conditions."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
GUARD_TEST = ROOT / "scripts" / "ci" / "guard.test.sh"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "promote-prod.yml",
    ROOT / ".github" / "workflows" / "run-prod-intelligence-daily-once.yml",
    ROOT / ".github" / "workflows" / "register-prod-eid.yml",
)
# A shell `test` command. jq's `test(` regex helper is not a guard.
_BARE_TEST = re.compile(r"(?m)(?:^|[;&|])\s*test(?:\s|$)")
_SECRET_MARKERS = ("secrets.", "PRIVATE_KEY", "PASSWORD", "TOKEN", "PASSPHRASE")
_ALLOWED_PENDING = (
    '[{"version":"V150","filename":"V150__prod_intelligence_raw_cleanup_authority.sql","sha256":"883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"}]',
    '[{"version":"V162","filename":"V162__prod_intelligence_proactive_cleanup.sql","sha256":"451eda0f76fe21fda15058b59d1868804f7c32a49f87b21d77dd5f3b45c4b557"}]',
    '[{"version":"V163","filename":"V163__prod_approved_metadata_feed_cleanup.sql","sha256":"1d4470c4eac4939bf4fbda4f56f0c8a1b004d6e9190d5512ae9e220e5b99b741"}]',
    '[{"version":"V164","filename":"V164__prod_intelligence_daily_activation_view.sql","sha256":"670dd90048d479b69bc2d032537333da785f85698ba71b64c75aed39b20043c9"}]',
    '[{"version":"V165","filename":"V165__prod_intelligence_daily_view_join_compatibility.sql","sha256":"1c5bdcdaaed21a0e5b44a57b224d536f623ee7c8ec15d35052224eb3c321b41d"}]',
    '[{"version":"V166","filename":"V166__prod_nih_news_daily_activation_view.sql","sha256":"6ebe428121436db840a357506003d654df82a159f02737d9ab10c52d7f41500c"}]',
    '[{"version":"V167","filename":"V167__prod_cdc_mmwr_daily_activation_view.sql","sha256":"cde1a5573525333f20bc847812bb3068493e81ec27b217b537dcf1a18d02c09f"}]',
    '[{"version":"V168","filename":"V168__api_diagnostics_history_views.sql","sha256":"18fd6c1ec8b2b6bf483a2e76ce2be08074a31038d6131b7d2a23a8456676a3f6"}]',
    '[{"version":"V169","filename":"V169__paper_policy_approval.sql","sha256":"1a70bbcf348f3f2daeaa6fde6522d86e26aee558235a5a6ca04a22023c4ea136"}]',
    '[{"version":"V170","filename":"V170__intelligence_source_activations.sql","sha256":"ada1e5cc76d389a2a18a930428277f84204301ec5afe63bf1c2b79c0fd7c271d"}]',
    '[{"version":"V173","filename":"V173__intelligence_feed_v2_description.sql","sha256":"fd0ab5e5351ebe453cd4cf941ffaa1326634baa1495450113e231deeff7b8156"}]',
    '[{"version":"V175","filename":"V175__intelligence_abstract_suppressions_feed_v2.sql","sha256":"5eb3b00effa0eae89c48ca0bd4c3ff7d2497929257cb077ee103b760c606f2e5"}]',
    '[{"version":"V150","filename":"V150__prod_intelligence_raw_cleanup_authority.sql","sha256":"883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"},{"version":"V162","filename":"V162__prod_intelligence_proactive_cleanup.sql","sha256":"451eda0f76fe21fda15058b59d1868804f7c32a49f87b21d77dd5f3b45c4b557"}]',
)


def test_guard_helper_shell_cases() -> None:
    result = subprocess.run(
        ["bash", str(GUARD_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "guard.sh tests passed"
    assert result.stderr == ""


def _run_scripts(path: Path) -> list[str]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    scripts: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            run = node.get("run")
            if isinstance(run, str):
                scripts.append(run)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return scripts


def test_governed_prod_workflows_have_no_bare_test_guards() -> None:
    offenders: list[str] = []
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        for match in _BARE_TEST.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.name}:{line_no}")
    assert offenders == []


def test_jq_regex_test_is_not_a_shell_guard() -> None:
    text = WORKFLOWS[0].read_text(encoding="utf-8")
    assert '.name | test("^catalog-registration-0[1-3]$")' in text
    assert _BARE_TEST.search(text) is None


def test_guard_steps_source_helper_before_use() -> None:
    for path in WORKFLOWS:
        for script in _run_scripts(path):
            guard_at = script.find("guard_")
            if guard_at < 0:
                continue
            source_at = script.find("source scripts/ci/guard.sh")
            assert source_at >= 0, path.name
            assert source_at < guard_at, path.name


def test_pending_allow_list_values_are_unchanged() -> None:
    text = WORKFLOWS[0].read_text(encoding="utf-8")
    for value in _ALLOWED_PENDING:
        assert text.count(value) == 1


def test_guard_calls_do_not_receive_secrets() -> None:
    for path in WORKFLOWS:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "guard_" not in line and "guard.sh" not in line:
                continue
            for marker in _SECRET_MARKERS:
                assert marker not in line, f"{path.name}:{line_no} contains {marker}"
