"""The sourced CI guard helper reports failures and preserves shell conditions."""

from __future__ import annotations

import os
import re
import stat
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
    '[{"version":"V170","filename":"V170__intelligence_source_activations.sql","sha256":"bbead62278450bf4b9f72074b9bf928c46ea789c1e7225b5b933814ff814246f"}]',
    '[{"version":"V171","filename":"V171__intelligence_item_topics.sql","sha256":"0bde46663f249afe562d6e9c202b7a5d52f3c2d83e72e112c727d82e01819185"}]',
    '[{"version":"V173","filename":"V173__intelligence_feed_v2_description.sql","sha256":"d1f1e2cd54980e20a44141e63b263696fd77c88e881012c9befcab955afc8fcf"}]',
    '[{"version":"V174","filename":"V174__intelligence_feed_v2_entrez_dedupe.sql","sha256":"056ef4d57cbde1fd851d0fe0e5af1b79264bf619274562c930a8998e0fd815d7"}]',
    '[{"version":"V175","filename":"V175__intelligence_abstract_suppressions_feed_v2.sql","sha256":"3dcdff4a16127e31778e47e787b38b3275a265770cf17b29280cb1f2c4f2dada"}]',
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


def test_daily_reopen_choices_accept_pubmed_only_on_a_later_attempt() -> None:
    path = ROOT / ".github" / "workflows" / "run-prod-intelligence-daily-once.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    source = document[True]["workflow_dispatch"]["inputs"]["source_id"]
    rss = (
        "cdc-eid-expedited",
        "cdc-eid-ahead-of-print",
        "cdc-outbreaks",
        "nih-news-releases",
        "cdc-mmwr",
    )
    pubmed = ("pubmed-tick-borne", "pubmed-lyme-borrelia")
    assert source["type"] == "choice"
    assert source["default"] == "none"
    assert source["options"][:1] == ["none"]
    assert tuple(source["options"][1:]) == (*rss, *pubmed)
    build = next(
        step["run"]
        for step in document["jobs"]["run"]["steps"]
        if step.get("name") == "Capture baseline and build one-shot spec"
    )
    rss_case = "|".join(rss) + ")"
    pubmed_case_pattern = "|".join(pubmed) + ")"
    assert build.count(rss_case) == 2
    assert build.count(pubmed_case_pattern) == 1
    assert "$rss_sources" not in build
    assert "$pubmed_sources" not in build
    reopen_at = build.find('REOPEN_ATTEMPT:-1}" -ge 2')
    pubmed_case = build.find(pubmed_case_pattern)
    attempt_one = build.find("INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID", pubmed_case)
    assert 0 <= reopen_at < pubmed_case < attempt_one
    recovery_at = build.find("INTELLIGENCE_DAILY_RECOVERY_SOURCE_REQUIRED")
    assert recovery_at < reopen_at
    assert pubmed_case_pattern not in build[recovery_at:reopen_at]


def test_guard_calls_do_not_receive_secrets() -> None:
    for path in WORKFLOWS:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "guard_" not in line and "guard.sh" not in line:
                continue
            for marker in _SECRET_MARKERS:
                assert marker not in line, f"{path.name}:{line_no} contains {marker}"


_DAILY_BUILD_STEP = "Capture baseline and build one-shot spec"
_REVIEWED_COMMIT = "a" * 40
_IMAGE_DIGEST = "sha256:" + "b" * 64
_DOCTL_STUB = """#!/bin/bash
set -euo pipefail
kind="$1 ${2:-} ${3:-}"
case "$kind" in
  "registry repository list-manifests")
    printf '[{"digest":"%s","tags":["sha-%s"]}]\\n' "$IMAGE_DIGEST" "$REVIEWED_COMMIT"
    ;;
  "apps spec get")
    if [[ "${4:-}" == "$PROD_APP_ID" ]]; then
      printf '{"jobs":[{"name":"intelligence-feed-daily","image":{"digest":"%s"}}]}\\n' \\
        "$IMAGE_DIGEST"
    else
      printf '{"jobs":[{"image":{"digest":"%s"}}]}\\n' "$IMAGE_DIGEST"
    fi
    ;;
  "apps get "*)
    printf '%s\\n' '[{"active_deployment":{"id":"dep-1"}}]'
    ;;
  "apps get-deployment"*)
    printf '%s\\n' '[{"phase":"ACTIVE"}]'
    ;;
  *)
    printf 'unexpected doctl %s\\n' "$*" >&2
    exit 1
    ;;
esac
"""
_GH_STUB = """#!/bin/bash
printf '%s\\n' 1
"""
_PYTHON_STUB = """#!/bin/bash
set -euo pipefail
printf '%s\\n' "$@" > "$PYTHON_ARGS_FILE"
output=""
previous=""
for arg in "$@"; do
  if [[ "$previous" == "--output" ]]; then
    output="$arg"
  fi
  previous="$arg"
done
if [[ -n "$output" ]]; then
  printf '%s\\n' '{}' > "$output"
fi
"""


def _daily_build_script() -> str:
    path = ROOT / ".github" / "workflows" / "run-prod-intelligence-daily-once.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return next(
        step["run"]
        for step in document["jobs"]["run"]["steps"]
        if step.get("name") == _DAILY_BUILD_STEP
    )


def _install_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_daily_source_selection_step_executes_literal_case_patterns(tmp_path: Path) -> None:
    """Run the workflow step itself. A variable "|" in `case` rejects every real id."""
    script = _daily_build_script()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_executable(bin_dir / "doctl", _DOCTL_STUB)
    _install_executable(bin_dir / "gh", _GH_STUB)
    _install_executable(bin_dir / "python", _PYTHON_STUB)
    # Attempt 2 on the PubMed recover case: the attempt-1 elif must not hide a leak.
    cases = (
        ("none", "none", "1", "", True),
        ("rss-reopen", "cdc-mmwr", "2", "", True),
        ("pubmed-reopen", "pubmed-tick-borne", "2", "", True),
        ("pubmed-first-attempt", "pubmed-tick-borne", "1", "", False),
        ("rss-recover", "cdc-mmwr", "1", "recover-run", True),
        ("pubmed-recover", "pubmed-tick-borne", "2", "recover-run", False),
    )
    for name, source_id, attempt, recover, accepted in cases:
        work = tmp_path / name
        work.mkdir()
        args_file = work / "python-args"
        env = {
            "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
            "HOME": str(tmp_path),
            "INTEL_DAILY_WORK": str(work),
            "PROD_APP_ID": "prod-app",
            "DEV_APP_ID": "dev-app",
            "REVIEWED_COMMIT": _REVIEWED_COMMIT,
            "IMAGE_DIGEST": _IMAGE_DIGEST,
            "GITHUB_REPOSITORY": "example/atlas",
            "PREFLIGHT_ONLY": "false",
            "SOURCE_ID": source_id,
            "REOPEN_ATTEMPT": attempt,
            "RECOVER_INGESTION_RUN_ID": recover,
            "PYTHON_ARGS_FILE": str(args_file),
        }
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        output = result.stdout + result.stderr
        if accepted:
            assert result.returncode == 0, f"{name}: {output}"
            assert "INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID" not in output
            args = args_file.read_text(encoding="utf-8").splitlines()
            assert (work / "ready").is_file(), name
        else:
            assert result.returncode != 0, name
            assert "INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID" in output, output
            assert not args_file.exists(), name
            assert not (work / "ready").exists(), name
            continue
        if name == "none":
            assert "--source" not in args
            assert "--reopen-attempt" not in args
            assert "--recover-ingestion-run-id" not in args
        elif name == "rss-reopen":
            assert args[args.index("--reopen-attempt") + 1] == "2"
            assert args[args.index("--source") + 1] == "cdc-mmwr"
            assert "--recover-ingestion-run-id" not in args
        elif name == "pubmed-reopen":
            assert args[args.index("--reopen-attempt") + 1] == "2"
            assert args[args.index("--source") + 1] == "pubmed-tick-borne"
            assert "--recover-ingestion-run-id" not in args
        elif name == "rss-recover":
            assert args[args.index("--recover-ingestion-run-id") + 1] == "recover-run"
            assert args[args.index("--source") + 1] == "cdc-mmwr"
            assert "--reopen-attempt" not in args
        else:
            raise AssertionError(name)
