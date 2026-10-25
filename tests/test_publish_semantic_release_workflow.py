"""Regression tests for the protected semantic-release workflow."""

from __future__ import annotations

from pathlib import Path

from semantic_contracts import load_workflow, trigger_map, workflow_runs

WORKFLOW = Path(".github/workflows/publish-semantic-release.yml")


def _document() -> dict:
    return load_workflow(WORKFLOW)


def _runs() -> str:
    return "\n".join(workflow_runs(_document()))


def test_release_operation_creates_its_own_ephemeral_connection_files() -> None:
    """Each Actions step must be independently executable and clean up secrets."""
    operation = _runs().split(
        "Build, publish, or rollback the semantic release and prove state", 1
    )[-1]
    assert 'trap \'rm -f "$key_file" "$config_file" "$january_manifest"\' EXIT' in operation
    assert "printf '%s' \"$SNOWFLAKE_PRIVATE_KEY_B64\" | fold -w 64" in operation
    assert 'cat > "$config_file" <<EOF' in operation
    assert 'private_key_path = "$key_file"' in operation
    assert 'test -f "$key_file"' not in operation
    assert 'test -f "$config_file"' not in operation


def test_default_release_id_matches_the_reviewed_manifest() -> None:
    release_id = trigger_map(_document())["workflow_dispatch"]["inputs"]["release_id"]
    assert release_id["default"] == "governed-2026-09-17-unknown-coverage"


def test_january_preparation_is_dev_build_only_and_job_local() -> None:
    document = _document()
    inputs = trigger_map(document)["workflow_dispatch"]["inputs"]
    assert "climate_review_commit" not in inputs
    assert "climate_review_url" not in inputs
    assert "climate_reviewer" not in inputs
    runs = _runs()
    assert 'if [[ "$PREPARE_JANUARY_CLIMATE" == "true" ]]; then' in runs
    assert 'test "${{ inputs.environment_name }}" = dev' in runs
    assert 'test "$OPERATION" = build' in runs
    assert (
        'test "$MANIFEST_PATH" = docs/contracts/climate/january-2025-dev-release-input.json' in runs
    )
    assert 'january_manifest="$RUNNER_TEMP/january-climate-release-manifest.json"' in runs
    assert '--output "$january_manifest"' in runs
    assert 'MANIFEST_PATH="$january_manifest"' in runs
    assert any(
        isinstance(step.get("env"), dict) and step["env"].get("GH_TOKEN") == "${{ github.token }}"
        for job in document["jobs"].values()
        for step in job.get("steps") or []
        if isinstance(step, dict)
    )
