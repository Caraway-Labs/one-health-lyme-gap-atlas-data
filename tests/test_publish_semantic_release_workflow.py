"""Regression tests for the protected semantic-release workflow."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/publish-semantic-release.yml")


def test_release_operation_creates_its_own_ephemeral_connection_files() -> None:
    """Each Actions step must be independently executable and clean up secrets."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    operation = workflow.split(
        "- name: Build, publish, or rollback the semantic release and prove state", 1
    )[1]

    assert 'trap \'rm -f "$key_file" "$config_file"\' EXIT' in operation
    assert "printf '%s' \"$SNOWFLAKE_PRIVATE_KEY_B64\" | fold -w 64" in operation
    assert 'cat > "$config_file" <<EOF' in operation
    assert 'private_key_path = "$key_file"' in operation
    assert 'test -f "$key_file"' not in operation
    assert 'test -f "$config_file"' not in operation
