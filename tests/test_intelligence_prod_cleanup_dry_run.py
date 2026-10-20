"""Exact synthetic pair inspection is SELECT/HEAD only, with no approval."""

import importlib.util
import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data import intelligence_raw_cleanup as cleanup_module
from lyme_gap_atlas_data.intelligence_items import canonical_json, identity_hash
from lyme_gap_atlas_data.intelligence_raw_cleanup import ObjectRawDelete
from lyme_gap_atlas_data.intelligence_raw_runtime import SnowflakeRawLedger
from lyme_gap_atlas_data.intelligence_retention import RawCopy, capture_lease

spec = importlib.util.spec_from_file_location(
    "prod_cleanup", Path(__file__).parents[1] / "scripts/intelligence_raw_cleanup_prod.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def snapshot(now="2026-09-01T00:00:00Z"):
    lease = capture_lease(
        source_id="cdc-eid-expedited",
        registry_version=1,
        source_sha256="a" * 64,
        capture_id=module.SYNTHETIC_RUN,
        artifact_sha256=module.SYNTHETIC_SHA,
        captured_at=now,
        policy_ref="reviewed-raw30",
        permitted=lambda *_: True,
    )
    copies = (
        RawCopy(
            "PROD",
            lease.source_id,
            "checkpoint_payload",
            f"snowflake://{module.DATABASE}/GOVERNANCE/INGESTION_RUN_PAYLOADS/{module.SYNTHETIC_RUN}",
            lease.sha256,
        ),
        RawCopy(
            "PROD",
            lease.source_id,
            "raw_object",
            f"s3://one-health-lyme-gap-atlas-data-prod/prod/prod/cdc-eid-expedited/{module.SYNTHETIC_RUN}/{module.SYNTHETIC_SHA}.bin",
            lease.sha256,
        ),
    )
    return SimpleNamespace(
        environment="PROD",
        copies=lambda: copies,
        claims=lambda copy: tuple(c for c in copies if c.physical_key == copy.physical_key),
        lease=lambda _: lease,
    )


def test_exact_pair_is_expired_at_30_days_and_requires_both_stores():
    gate = snapshot()
    plan = module.synthetic_plan(gate, "2026-10-01T00:00:00Z")
    assert len(plan.copies) == 2
    with pytest.raises(PermissionError, match="EXACT_SYNTHETIC_PAIR"):
        module.synthetic_plan(gate, "2026-09-30T23:59:59Z")
    copies = gate.copies()
    gate.copies = lambda: copies[:1]
    with pytest.raises(PermissionError, match="EXACT_SYNTHETIC_PAIR"):
        module.synthetic_plan(gate, "2026-10-01T00:00:00Z")


def test_extra_expired_target_refuses_instead_of_silently_filtering():
    gate = snapshot()
    copies = gate.copies()
    extra = replace(copies[0], locator=copies[0].locator.replace(module.SYNTHETIC_RUN, "other-run"))
    gate.copies = lambda: copies + (extra,)
    gate.claims = lambda copy: tuple(
        c for c in gate.copies() if c.physical_key == copy.physical_key
    )
    with pytest.raises(PermissionError, match="EXACT_SYNTHETIC_PAIR"):
        module.synthetic_plan(gate, "2026-10-01T00:00:00Z")


@pytest.mark.parametrize("code", ["403", "AccessDenied", "500"])
def test_head_errors_are_not_absence_and_never_delete(code):
    gate = snapshot()

    class Client:
        def head_object(self, **kwargs):
            error = RuntimeError("private provider detail")
            error.response = {"Error": {"Code": code}}
            raise error

        def delete_object(self, **kwargs):
            pytest.fail("read-only probe deleted")

    driver = ObjectRawDelete(
        gate, Client(), bucket="one-health-lyme-gap-atlas-data-prod", prefix="prod"
    )
    with pytest.raises(RuntimeError):
        driver.exists(gate.copies()[1])


def test_delete_response_without_absence_is_failure():
    gate = snapshot()
    client = SimpleNamespace(
        head_object=lambda **_: {},
        delete_object=lambda **_: {},
        list_object_versions=lambda **_: {},
    )
    driver = ObjectRawDelete(
        gate, client, bucket="one-health-lyme-gap-atlas-data-prod", prefix="prod"
    )
    with pytest.raises(PermissionError, match="DELETE_NOT_CONFIRMED"):
        driver(gate.copies()[1])


def test_snapshot_rejects_tampered_or_duplicate_documents(monkeypatch):
    gate = snapshot()
    doc = asdict(gate.copies()[0])
    row = {
        "KIND": "copy",
        "KEY": "copy-key",
        "SHA": identity_hash(doc),
        "DOCUMENT": canonical_json(doc),
    }
    monkeypatch.setattr(module, "inspection_query", lambda _: [row, row])
    with pytest.raises(PermissionError, match="LEDGER_INVALID"):
        module.inspection_snapshot()
    monkeypatch.setattr(module, "inspection_query", lambda _: [{**row, "SHA": "0" * 64}])
    with pytest.raises(PermissionError, match="LEDGER_INVALID"):
        module.inspection_snapshot()


def test_dry_run_reads_pair_without_writes_and_does_not_overwrite(monkeypatch, tmp_path, capsys):
    gate = snapshot()
    queries = []

    def query(sql):
        queries.append(sql)
        assert sql.startswith("SELECT ")
        if "CURRENT_USER" in sql:
            return [
                {
                    "U": "MATTHEWCARAWAY",
                    "R": "OH_LYME_PROD_RUNTIME",
                    "D": module.DATABASE,
                    "W": module.WAREHOUSE,
                }
            ]
        return [{"N": 1, "MATCHED": 1}]

    events = []
    client = SimpleNamespace(
        head_object=lambda **_: events.append("head"), list_object_versions=lambda **_: {}
    )
    monkeypatch.setattr(module, "inspection_query", query)
    monkeypatch.setattr(module, "inspection_snapshot", lambda: gate)
    monkeypatch.setattr(module.boto3, "client", lambda *_, **__: client)
    monkeypatch.setenv("INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID", "test-only")
    monkeypatch.setenv("INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY", "test-only")
    path = tmp_path / "plan.json"
    module.dry_run(path)
    result = json.loads(capsys.readouterr().out)
    assert result["copy_count"] == 2
    assert result["writes"] is False and result["deletes"] is False
    assert result["executor_identity_proven"] is False
    assert events == ["head"]
    assert len(queries) == 2
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        module.dry_run(path)
    assert path.read_bytes() == before


def test_wrong_identity_stops_before_inventory_or_spaces(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "inspection_query", lambda _: [])
    monkeypatch.setattr(module, "inspection_snapshot", lambda: pytest.fail("inventory read"))
    with pytest.raises(PermissionError, match="INSPECTION_IDENTITY"):
        module.dry_run(tmp_path / "plan.json")


@pytest.mark.parametrize(
    "result",
    [
        {"IsTruncated": True},
        {"DeleteMarkers": [{"VersionId": "marker"}]},
        {"Versions": [{"Key": "other", "VersionId": "null"}]},
        {"Versions": [{"Key": "any", "VersionId": "old-version"}]},
    ],
)
def test_version_history_never_uses_unversioned_delete(result):
    gate = snapshot()
    client = SimpleNamespace(list_object_versions=lambda **_: result)
    driver = ObjectRawDelete(
        gate, client, bucket="one-health-lyme-gap-atlas-data-prod", prefix="prod"
    )
    with pytest.raises(PermissionError, match="VERSIONED_OBJECT_UNSUPPORTED"):
        driver(gate.copies()[1])


def test_inspection_cli_is_named_pat_bounded_and_redacts_failure(monkeypatch):
    def invoke(args, **kwargs):
        assert args[:5] == ["snow", "sql", "-c", "ATLAS_PROD_RUNTIME_AUDIT", "--role"]
        assert kwargs["timeout"] == 45 and kwargs["capture_output"] is True
        raise module.subprocess.CalledProcessError(1, args, stderr="private provider detail")

    monkeypatch.setattr(module.subprocess, "run", invoke)
    with pytest.raises(PermissionError, match="^INTELLIGENCE_RAW_INSPECTION_UNAVAILABLE$"):
        module.inspection_query("SELECT 1")


def test_missing_dedicated_spaces_key_stops_before_any_spaces_call(monkeypatch, tmp_path):
    monkeypatch.setattr(
        module,
        "inspection_query",
        lambda _: [
            {
                "U": "MATTHEWCARAWAY",
                "R": "OH_LYME_PROD_RUNTIME",
                "D": module.DATABASE,
                "W": module.WAREHOUSE,
            }
        ],
    )
    monkeypatch.setattr(module, "inspection_snapshot", snapshot)
    monkeypatch.delenv("INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setattr(
        module.boto3, "client", lambda *_, **__: pytest.fail("Spaces client created")
    )
    path = tmp_path / "plan.json"
    with pytest.raises(PermissionError, match="INSPECTION_CREDENTIAL_REQUIRED"):
        module.dry_run(path)
    assert not path.exists()


def test_version_preflight_stops_before_checkpoint_cleanup(monkeypatch):
    snap = snapshot()
    plan = module.synthetic_plan(snap, "2026-10-01T00:00:00Z")
    gate = SimpleNamespace(
        environment="PROD",
        lease=snap.lease,
        ledger=SnowflakeRawLedger(lambda: None, "PROD", expected_role=module.EXECUTOR_ROLE),
    )
    client = SimpleNamespace(list_object_versions=lambda **_: {"IsTruncated": True})
    monkeypatch.setattr(cleanup_module, "verify_prod_cleanup_handoff", lambda _: None)
    monkeypatch.setattr(
        cleanup_module, "cleanup", lambda *_, **__: pytest.fail("checkpoint cleanup entered")
    )
    with pytest.raises(PermissionError, match="VERSIONED_OBJECT_UNSUPPORTED"):
        cleanup_module.execute_reviewed_prod_plan(
            gate,
            plan,
            factory=lambda: None,
            spaces_client=client,
            bucket="one-health-lyme-gap-atlas-data-prod",
            prefix="prod",
        )
