"""Exercise the actual builder/CLI failure boundary without network or credentials."""

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data import cli, failure_runtime, semantic_release
from lyme_gap_atlas_data.failure_evidence import validate_packet

ROOT = Path(__file__).resolve().parents[1]


def context_file(tmp_path):
    path = tmp_path / "reviewed.json"
    packet = json.loads((ROOT / "docs/delivery/failures/pr-336.json").read_text())
    path.write_text(json.dumps(packet))
    return path


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("exception rendering forbidden")


@pytest.mark.parametrize(
    "mode", ["disabled", "valid", "hostile", "collision", "missing", "oversize"]
)
def test_actual_builder_rolls_back_once_preserves_original(mode, tmp_path, monkeypatch, capsys):
    error = PrivateFailure()
    events = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def autocommit(self, value):
            events.append(("autocommit", value))

        def cursor(self):
            return self

        def execute(self, query, params):
            events.append("write")
            raise error

        def rollback(self):
            events.append("rollback")

        def commit(self):
            events.append("commit")

    manifest = SimpleNamespace(raw={}, release_id="synthetic", sources=(), source=lambda key: None)
    monkeypatch.setattr(cli, "_settings", lambda: SimpleNamespace(snowflake_database="LOCAL"))
    monkeypatch.setattr(semantic_release, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(semantic_release, "connect", lambda settings: Connection())
    monkeypatch.setattr(semantic_release, "_assert_release_absent", lambda *args: None)
    for name in (
        "_verify_pathogen_parity_classification",
        "_verify_evidence_only_coverage_classification",
        "_verify_tick_parity_classification",
    ):
        monkeypatch.setattr(semantic_release, name, lambda *args, **kwargs: None)
    # The source read comprehension must have the keys needed by the real builder.
    manifest.sources = tuple(SimpleNamespace(source_key=key) for key in ("pathogen", "tick"))
    monkeypatch.setattr(semantic_release, "_verify_source_gate", lambda *args, **kwargs: None)
    monkeypatch.setattr(semantic_release, "_read_source_rows", lambda *args: [])
    monkeypatch.setattr(semantic_release, "_assemble_counties", lambda *args, **kwargs: ([{}], []))
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 1)
    monkeypatch.setattr(semantic_release, "_bundle_sha256", lambda *args: "a" * 64)
    monkeypatch.setattr(
        semantic_release,
        "_insert_release",
        lambda cursor, *args: cursor.execute("INSERT synthetic", ("private parameter",)),
    )
    context = context_file(tmp_path)
    output = tmp_path / "packet.json"
    if mode == "hostile":
        context.write_text('{"operation":"SEMANTIC_RELEASE","secret":"private parameter"}')
    if mode == "oversize":
        context.write_bytes(b"x" * (failure_runtime.MAX_PACKET_BYTES + 1))
    if mode == "collision":
        output.write_text("existing attempt")
    if mode == "missing":
        context.unlink()
    if mode == "disabled":
        context = output = None
    with pytest.raises(PrivateFailure) as caught:
        cli.semantic_release_build_command(Path("unused"), context, output)
    assert caught.value is error
    assert events == [("autocommit", False), "write", "rollback"]
    names = []
    tb = caught.value.__traceback__
    while tb:
        names.append(tb.tb_frame.f_code.co_name)
        tb = tb.tb_next
    assert "build_semantic_release" in names and "execute" in names
    text = capsys.readouterr()
    assert "private parameter" not in text.out + text.err
    if mode == "valid":
        packet = json.loads(output.read_text())
        validate_packet(packet)
        assert packet["identity"]["workload_sha"]["state"] == "UNKNOWN"
        assert "COLLECTED" in text.err
    elif mode == "collision":
        assert output.read_text() == "existing attempt"
    elif output:
        assert not output.exists()


def test_success_does_not_read_context_or_write_packet(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_settings", lambda: None)
    monkeypatch.setattr(cli, "build_semantic_release", lambda *args: {"status": "CANDIDATE"})
    monkeypatch.setattr(
        cli, "collect_runtime_failure", lambda *args: pytest.fail("unexpected collection")
    )
    cli.semantic_release_build_command(Path("unused"), tmp_path / "missing", tmp_path / "packet")
    assert json.loads(capsys.readouterr().out) == {"status": "CANDIDATE"}


def test_partial_configuration_is_constant_and_no_io(tmp_path):
    assert (
        failure_runtime.collect_runtime_failure(tmp_path / "missing", None)
        == "COLLECTION_UNAVAILABLE"
    )


def test_sink_size_rejected(tmp_path, monkeypatch):
    packet = json.loads(context_file(tmp_path).read_text())
    monkeypatch.setattr(failure_runtime, "MAX_PACKET_BYTES", 1)
    with pytest.raises(ValueError, match="failure collection unavailable"):
        failure_runtime.write_packet(tmp_path / "packet", packet)
    assert not (tmp_path / "packet").exists()


def test_unexpected_collector_error_preserves_failure(monkeypatch):
    error = PrivateFailure()
    monkeypatch.setattr(cli, "_settings", lambda: None)

    def fail(*args):
        raise error

    monkeypatch.setattr(cli, "build_semantic_release", fail)
    monkeypatch.setattr(
        cli, "collect_runtime_failure", lambda *args: (_ for _ in ()).throw(RuntimeError())
    )
    with pytest.raises(PrivateFailure) as caught:
        cli.semantic_release_build_command(Path("unused"), None, None)
    assert caught.value is error


@pytest.mark.parametrize("payload", [b"not json", b"\xff", b"[]", b'{"operation":"SOURCE_RUN"}'])
def test_invalid_metadata_is_redaction_rejected(payload, tmp_path):
    context = tmp_path / "context"
    context.write_bytes(payload)
    assert (
        failure_runtime.collect_runtime_failure(context, tmp_path / "out") == "REDACTION_REJECTED"
    )
    assert not (tmp_path / "out").exists()


def test_cli_opt_in_help():
    from typer.testing import CliRunner

    result = CliRunner().invoke(cli.app, ["pipeline", "semantic-release-build", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "--failure-context" in plain and "--failure-packet" in plain


def test_interrupted_output_retains_uncertain_partial_file(tmp_path, monkeypatch):
    packet = json.loads(context_file(tmp_path).read_text())
    original = failure_runtime.os.fdopen

    class InterruptedWriter:
        def __init__(self, descriptor):
            self.stream = original(descriptor, "wb")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, payload):
            self.stream.write(payload[:8])
            raise OSError("synthetic write failure")

    monkeypatch.setattr(
        failure_runtime.os, "fdopen", lambda descriptor, mode: InterruptedWriter(descriptor)
    )
    output = tmp_path / "packet"
    with pytest.raises(OSError):
        failure_runtime.write_packet(output, packet)
    assert (
        output.read_bytes()
        == (json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n").encode()[:8]
    )


@pytest.mark.parametrize("replacement_kind", ["regular", "symlink"])
def test_input_swap_between_lstat_and_open_rejected(replacement_kind, tmp_path, monkeypatch):
    context = context_file(tmp_path)
    target = tmp_path / "other-reviewed-content"
    target.write_bytes(context.read_bytes())
    replacement = tmp_path / "replacement"
    if replacement_kind == "symlink":
        try:
            replacement.symlink_to(target)
        except OSError:
            pytest.skip("Windows host does not permit test symlink creation")
    else:
        replacement.write_bytes(target.read_bytes())
    original = failure_runtime._open_no_follow
    calls = []

    def swap_then_open(path):
        calls.append("open")
        context.rename(tmp_path / "original")
        replacement.rename(context)
        return original(path)

    monkeypatch.setattr(failure_runtime, "_open_no_follow", swap_then_open)
    output = tmp_path / "out"
    assert failure_runtime.collect_runtime_failure(context, output) == "COLLECTION_UNAVAILABLE"
    assert calls == ["open"]
    assert not output.exists()


def test_wrong_open_descriptor_rejected_before_read(tmp_path, monkeypatch):
    context = context_file(tmp_path)
    other = tmp_path / "other"
    other.write_bytes(context.read_bytes())
    monkeypatch.setattr(
        failure_runtime, "_open_no_follow", lambda path: os.open(other, os.O_RDONLY)
    )
    assert (
        failure_runtime.collect_runtime_failure(context, tmp_path / "out")
        == "COLLECTION_UNAVAILABLE"
    )
    assert not (tmp_path / "out").exists()


def test_failed_writer_never_deletes_replacement(tmp_path, monkeypatch):
    packet = json.loads(context_file(tmp_path).read_text())
    original = failure_runtime.os.fdopen
    output = tmp_path / "packet"
    displaced = tmp_path / "displaced-partial"

    class SwappingWriter:
        def __init__(self, descriptor):
            self.stream = original(descriptor, "wb")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, payload):
            self.stream.write(payload[:8])
            self.stream.close()
            output.rename(displaced)
            output.write_bytes(b"another writer's replacement")
            raise OSError("synthetic write failure")

    monkeypatch.setattr(
        failure_runtime.os, "fdopen", lambda descriptor, mode: SwappingWriter(descriptor)
    )
    with pytest.raises(OSError):
        failure_runtime.write_packet(output, packet)
    assert output.read_bytes() == b"another writer's replacement"
    assert len(displaced.read_bytes()) == 8
