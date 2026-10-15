"""Offline January PROD boundary tests; none establish live PROD acceptance."""

import copy
import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from test_climate_release import extension
from test_routine_public_source_evidence import _S3, _Connection, _settings
from test_semantic_metadata import seal

from lyme_gap_atlas_data import climate_prod_binding as prod
from lyme_gap_atlas_data import climate_release as release
from lyme_gap_atlas_data import january_prod_evidence as evidence
from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.ingestion.adapters import AcquireResult, AcquisitionArtifact
from lyme_gap_atlas_data.ingestion.nclimgrid_daily import NOAA_MEMBER, TIGER_MEMBER, RetainedInputs
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import ValidationResult

ROOT = Path(__file__).parents[1]
RUN = "d0e1e30b-49f1-5400-8345-af0b3e975114"
EVIDENCE_RUN = "49f7fdb1-7fe1-4e44-9311-450c02ee3511"


def prod_extension(monkeypatch):
    monkeypatch.setattr(release, "ROW_COUNT", 1)
    result = extension()
    result.update(contract_version=prod.CONTRACT, target_environment="prod", ingestion_run_id=RUN)
    result["source_evidence"] = {}
    for index, key in enumerate(("noaa", "tiger"), 1):
        source = result["sources"][key]
        source["source_version_id"] = f"00000000-0000-4000-8000-{index:012d}"
        member = NOAA_MEMBER if key == "noaa" else TIGER_MEMBER
        suffix = hashlib.sha256(member.encode()).hexdigest()[:32]
        source["artifact_id"] = f"noaa_nclimgrid_daily_202501:{RUN}:{suffix}"
        result["source_evidence"][key] = {
            "ingestion_run_id": EVIDENCE_RUN,
            "artifact_id": f"evidence-{key}",
        }
    for item in result["metadata"]:
        item["provenance"]["source_version_id"]["value"] = result["sources"]["noaa"][
            "source_version_id"
        ]
        seal(item)
    return result


def test_prod_v2_requires_native_run_and_dev_contract_stays_pinned(monkeypatch):
    document = prod_extension(monkeypatch)
    release.validate_extension(document)
    document["ingestion_run_id"] = release.RUN_ID
    with pytest.raises(ValueError):
        release.validate_extension(document)
    legacy = extension()
    legacy["ingestion_run_id"] = RUN
    with pytest.raises(ValueError, match="CLIMATE_RUN"):
        release.validate_extension(legacy)


@pytest.mark.parametrize("recorded_count", [0, 1, 3])
def test_prod_metadata_cannot_bypass_recorded_owner_acceptance(monkeypatch, recorded_count):
    document = prod_extension(monkeypatch)
    for item in document["metadata"][:recorded_count]:
        item["steward_review"]["acceptance_recorded_at"] = {"state": "KNOWN", "value": "2026-10-09"}
    cursor = Mock()
    with pytest.raises(ValueError, match="CLIMATE_PROD_ACCEPTANCE_RECORDING_REQUIRED"):
        release.verify_recorded_acceptance(cursor, document)
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("mutation", ["source", "evidence", "decision", "missing", "duplicate"])
def test_native_publication_lineage_must_match_exact_source_approval(monkeypatch, mutation):
    document = prod_extension(monkeypatch)
    approvals = {
        key: {
            **document["source_evidence"][key],
            "source_version_id": source["source_version_id"],
            "decision_id": f"decision-{key}",
        }
        for key, source in document["sources"].items()
    }
    if mutation == "source":
        approvals["noaa"]["source_version_id"] = "unrelated"
    elif mutation == "evidence":
        approvals["tiger"]["artifact_id"] = "unrelated"
    elif mutation == "decision":
        approvals["noaa"]["decision_id"] = "unrelated"
    elif mutation == "missing":
        approvals.pop("tiger")
    cursor = Mock()
    lineage = [(json.dumps({"source_approvals": approvals}),)]
    cursor.fetchall.side_effect = [
        lineage * (2 if mutation == "duplicate" else 1),
        [("decision-noaa",)],
        [("decision-tiger",)],
    ]
    with pytest.raises(ValueError, match="CLIMATE_PROD_CAPTURE_LINEAGE"):
        prod.verify_capture_binding(cursor, document)


def test_matching_native_publication_lineage_is_accepted(monkeypatch):
    document = prod_extension(monkeypatch)
    approvals = {
        key: {
            **document["source_evidence"][key],
            "source_version_id": source["source_version_id"],
            "decision_id": f"decision-{key}",
        }
        for key, source in document["sources"].items()
    }
    cursor = Mock()
    cursor.fetchall.side_effect = [
        [({"source_approvals": approvals},)],
        [("decision-noaa",)],
        [("decision-tiger",)],
    ]
    prod.verify_capture_binding(cursor, document)
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)


def binary_fixture(monkeypatch):
    definition = load_source_definition(
        ROOT / "config/sources/noaa_nclimgrid_daily_202501_prod.yml"
    )
    noaa, tiger = b"fixture-netcdf", b"fixture-zip"
    noaa_sha, tiger_sha = hashlib.sha256(noaa).hexdigest(), hashlib.sha256(tiger).hexdigest()
    monkeypatch.setattr(evidence, "NOAA_SHA", noaa_sha)
    monkeypatch.setattr(evidence, "TIGER_SHA", tiger_sha)
    definition = replace(
        definition, extra={**definition.extra, "noaa_sha256": noaa_sha, "tiger_sha256": tiger_sha}
    )
    acquisition = AcquireResult(
        noaa,
        noaa_sha,
        "application/x-netcdf",
        artifacts=(
            AcquisitionArtifact(
                NOAA_MEMBER,
                noaa,
                "application/x-netcdf",
                definition.endpoint_template,
                "SOURCE_PAYLOAD",
            ),
            AcquisitionArtifact(
                TIGER_MEMBER,
                tiger,
                "application/zip",
                definition.extra["tiger_url"],
                "ANALYSIS_REFERENCE",
            ),
        ),
    )
    return definition, acquisition


@pytest.mark.parametrize(
    "mutation", ["bytes", "role", "url", "missing", "extra", "header", "payload"]
)
def test_binary_evidence_rejects_changed_or_ambiguous_package(monkeypatch, mutation):
    definition, acquired = binary_fixture(monkeypatch)
    acquired = copy.deepcopy(acquired)
    if mutation == "bytes":
        acquired.artifacts[0].payload = b"changed"
    elif mutation == "role":
        acquired.artifacts[1].request_purpose = "SOURCE_PAYLOAD"
    elif mutation == "url":
        acquired.artifacts[1].source_uri = "https://example.com/substitute.zip"
    elif mutation == "missing":
        acquired.artifacts = acquired.artifacts[:1]
    elif mutation == "extra":
        acquired.artifacts += acquired.artifacts[:1]
    elif mutation == "header":
        acquired.artifact_sha256 = "a" * 64
    else:
        acquired.payload = b"unrelated"
    with pytest.raises(ValueError):
        evidence.binary_evidence(definition, acquired)


def test_collector_preserves_binary_members_and_creates_only_pending_candidates(monkeypatch):
    from lyme_gap_atlas_data import source_evidence as collector

    definition, acquisition = binary_fixture(monkeypatch)
    connection, spaces = _Connection(), _S3()
    adapter = Mock()
    adapter.acquire.return_value = acquisition

    def validate(_definition, payload):
        assert isinstance(payload, RetainedInputs)
        return ValidationResult(ok=True)

    adapter.validate_payload.side_effect = validate
    monkeypatch.setattr(collector, "get_adapter", lambda _: adapter)
    monkeypatch.setattr(prod, "verify_execution_resource", lambda *args: None)
    receipt = collector.collect_routine_public_source_evidence(
        definition,
        settings=_settings(),
        connection_factory=lambda: connection,
        spaces_client=spaces,
    )
    assert len(spaces.objects) == 3
    assert {item["Body"] for item in spaces.objects} >= {b"fixture-netcdf", b"fixture-zip"}
    sql = "\n".join(query for query, _ in connection.cursor_instance.calls)
    assert "DATA_SOURCE_VERSIONS" not in sql and "MANUAL_REVIEW_DECISIONS" not in sql
    assert "RAW.GOVERNED_SOURCE_RECORDS" not in sql
    assert receipt["reference_artifact_id"] != receipt["source_artifact_id"]
    assert connection.committed


def test_climate_only_runner_leaves_v150_pending(monkeypatch):
    canonical = {item.version: item for item in migrations.load_migrations()}
    plan = [canonical[key] for key in ("V150", "V151", "V152")]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *_: set())
    cursor, connection = Mock(), Mock()
    cursor.fetchall.return_value = []
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *args, **kwargs: nullcontext(connection))
    pending = [
        {"version": item.version, "filename": item.filename, "sha256": item.sha256} for item in plan
    ]
    assert migrations.apply_migrations(
        Mock(), migrations.PROD_DATABASE, expected_pending=pending, january_climate_only=True
    ) == ["V151", "V152"]
    assert connection.execute_string.call_count == 2
    assert not any(
        "SP_DELETE_EXPIRED_INTELLIGENCE_RAW" in call.args[0]
        for call in connection.execute_string.call_args_list
    )
    with pytest.raises(PermissionError):
        migrations.apply_migrations(Mock(), migrations.PROD_DATABASE, expected_pending=pending)


def test_january_mutation_workflows_keep_explicit_scope_and_protected_environment():
    promote = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    assert "january_climate_only != true" in promote["jobs"]["promote"]["if"]
    assert promote["jobs"]["january-climate"]["environment"] == "production"
    release_workflow = (ROOT / ".github/workflows/publish-semantic-release.yml").read_text()
    assert 'if [[ "${{ inputs.january_prod_delivery }}" == true ]]; then' in release_workflow
    assert "require_schema(cursor)" in release_workflow
    assert "3600s" in release_workflow
    for version in ("V151", "V152"):
        assert version not in {
            item["version"] for item in migrations.migration_plan(migrations.DEV_DATABASE)
        }
        assert migrations.migration_execution_role(
            next(item for item in migrations.load_migrations() if item.version == version),
            migrations.PROD_DATABASE,
        ) == ("OH_LYME_PROD_OWNER" if version == "V151" else None)


def test_prod_prepare_preserves_entire_existing_nlcd_release(monkeypatch):
    from lyme_gap_atlas_data import climate_prod_manifest as manifest

    document = prod_extension(monkeypatch)
    annual = json.loads(
        (
            ROOT
            / "docs/contracts/semantic-release/governed-2026-10-06-nlcd-demo-cohort-manifest.json"
        ).read_text()
    )
    packet = json.loads(
        (ROOT / "docs/contracts/climate/january-2025-recorded-metadata-candidate.json").read_text()
    )
    cursor = Mock()
    cursor.fetchone.return_value = (
        "OH_LYME_PROD_MIGRATION_DEPLOY_SVC",
        "OH_LYME_PROD_MIGRATION_DEPLOYER",
        prod.PROD,
    )
    cursor.fetchall.side_effect = [
        [("PUBLISHED", manifest.BASE_BUNDLE, annual)],
        [
            (document["sources"]["noaa"]["artifact_id"], release.NOAA_SHA, 61013299),
            (document["sources"]["tiger"]["artifact_id"], release.TIGER_SHA, 83989800),
        ],
        [(document["sources"]["noaa"]["source_version_id"], EVIDENCE_RUN, "evidence-noaa")],
        [(document["sources"]["tiger"]["source_version_id"], EVIDENCE_RUN, "evidence-tiger")],
    ]
    monkeypatch.setattr(manifest, "ROW_COUNT", 1)
    monkeypatch.setattr(
        manifest, "read_capture_membership", lambda *a, **kw: (["e" * 64], "b" * 64)
    )
    monkeypatch.setattr(manifest, "canonical_partitions", lambda *a, **kw: iter(()))
    monkeypatch.setattr(
        manifest, "project_verified_partitions", lambda *a, **kw: {"projection_sha256": "a" * 64}
    )
    # Live acceptance is separately exercised; this test isolates manifest composition.
    verified = Mock()
    monkeypatch.setattr(manifest, "verify_extension", verified)
    result = manifest.prepare(cursor, manifest.SPEC, packet, document["review_evidence"])
    assert result["nlcd_extension"] == annual["nlcd_extension"]
    assert result["sources"] == annual["sources"]
    assert result["score_defaults"] == annual["score_defaults"]
    assert result["limitations"] == annual["limitations"]
    assert result["climate_extension"]["ingestion_run_id"] == RUN
    assert (
        result["climate_extension"]["source_evidence"]["noaa"]["ingestion_run_id"] == EVIDENCE_RUN
    )
    verified.assert_called_once_with(cursor, result["climate_extension"], database=prod.PROD)


@pytest.mark.parametrize(
    "change", [None, "account", "region", "warehouse", "size", "generation", "qas", "suspend"]
)
def test_execution_resource_requires_bound_account_and_observed_capacity(change):
    identity = [
        "OH_LYME_PROD_PIPELINE_SVC",
        "OH_LYME_PROD_RUNTIME",
        prod.PROD,
        "OH_LYME_PROD_APPROVAL_XS_WH",
        "AWS_US_WEST_2",
        "TXB06009",
    ]
    warehouse = {
        "name": identity[3],
        "size": "X-Small",
        "type": "STANDARD",
        "generation": "2",
        "auto_suspend": 60,
    }
    if change in {"account", "region", "warehouse"}:
        identity[{"account": 5, "region": 4, "warehouse": 3}[change]] = "UNRELATED"
    elif change == "size":
        warehouse["size"] = "Large"
    elif change == "generation":
        warehouse.pop("generation")
    elif change == "qas":
        warehouse["enable_query_acceleration"] = True
    elif change == "suspend":
        warehouse["auto_suspend"] = 600
    cursor = Mock()
    cursor.fetchone.return_value = tuple(identity)
    cursor.description = [(key,) for key in warehouse]
    cursor.fetchall.return_value = [tuple(warehouse.values())]
    if change is None:
        prod.verify_execution_resource(cursor, identity[1], identity[0])
    else:
        with pytest.raises(ValueError):
            prod.verify_execution_resource(
                cursor, "OH_LYME_PROD_RUNTIME", "OH_LYME_PROD_PIPELINE_SVC"
            )
    assert all(
        call.args[0].startswith(("SELECT", "SHOW")) for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize(
    "operation,prepare,release_id,expected",
    [
        ("build", "true", "governed-2026-10-15-january-climate-prod", 0),
        ("publish", "false", "governed-2026-10-15-january-climate-prod", 0),
        ("rollback", "false", "governed-2026-10-06-nlcd-demo-cohort", 0),
        ("publish", "true", "governed-2026-10-15-january-climate-prod", 1),
        ("publish", "false", "unrelated-release", 1),
    ],
)
def test_protected_january_release_input_validation_executes_without_mutation(
    operation, prepare, release_id, expected
):
    import os
    import shutil
    import subprocess

    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for executable workflow input validation")
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-semantic-release.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["semantic-release"]["steps"]
        if step.get("name") == "Validate protected operation inputs"
    )
    script = (
        step["run"]
        .replace("${{ inputs.release_commit }}", "a" * 40)
        .replace("${{ inputs.environment_name }}", "production")
        .replace("${{ inputs.bounded_delivery }}", "true")
    )
    result = subprocess.run(
        [bash, "-c", script],
        env={
            **os.environ,
            "JANUARY_PROD_DELIVERY": "true",
            "PREPARE_JANUARY_CLIMATE": prepare,
            "MANIFEST_PATH": "docs/contracts/climate/january-2025-prod-release-input.json",
            "OPERATION": operation,
            "RELEASE_ID": release_id,
            "CONFIRM": "true",
            "REASON": "Offline scope fixture",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected, result.stderr


@pytest.mark.parametrize("mutation", [None, "missing_tavg", "derived_tavg", "null_zero", "ak_zero"])
def test_production_readback_requires_real_four_measure_values_and_missingness(
    monkeypatch, mutation
):
    from lyme_gap_atlas_data import climate_prod_manifest as manifest

    monkeypatch.setattr(prod, "verify_execution_resource", lambda *args: None)
    samples, metadata = [], []
    for key, value in {
        "prcp": 0,
        "tmin": -1.992294192037333,
        "tmax": 16.29939307942125,
        "tavg": 7.153611977327104,
    }.items():
        measure = f"nclimgrid_{key}_county_day"
        metadata.append(
            {
                "release_id": manifest.RELEASE,
                "measure_id": measure,
                "metadata_revision_id": key,
                "unit": "mm" if key == "prcp" else "degree_Celsius",
            }
        )
        for county in ("48277", "02013"):
            samples.append(
                {
                    "release_id": manifest.RELEASE,
                    "measure_id": measure,
                    "county_fips": county,
                    "period_start": "2025-01-17",
                    "period_end": "2025-01-17",
                    "value": value if county == "48277" else None,
                    "unit": "mm" if key == "prcp" else "degree_Celsius",
                    "coverage_status": "COMPLETE"
                    if county == "48277"
                    else "OUT_OF_SOURCE_COVERAGE",
                    "value_state": ("ZERO" if key == "prcp" else "OBSERVED")
                    if county == "48277"
                    else "UNAVAILABLE",
                    "source_published_at": None,
                    "metadata_revision_id": key,
                    "atlas_acquired_at": "2026-10-15",
                }
            )
    if mutation == "missing_tavg":
        samples.pop()
    elif mutation == "derived_tavg":
        samples[-2]["value"] = (16.29939307942125 - 1.992294192037333) / 2
    elif mutation == "null_zero":
        samples[0]["value"] = None
    elif mutation == "ak_zero":
        samples[1]["value"] = 0
    releases = [{"release_id": manifest.RELEASE, "status": "PUBLISHED", "climate_run": RUN}]

    class Cursor:
        sfqid = "offline-fixture"

        def __init__(self):
            self.results = iter((samples, metadata, releases))
            self.calls = []

        def execute(self, sql):
            assert sql.startswith("SELECT") and " LIMIT " in sql
            assert "ONE_HEALTH_LYME_GAP_ATLAS_DEV" not in sql
            self.calls.append(sql)
            self.rows = next(self.results)
            self.description = [(key,) for key in self.rows[0]]

        def fetchall(self):
            return [tuple(row.values()) for row in self.rows]

    cursor = Cursor()
    if mutation is None:
        result = manifest.verify_published(cursor)
        assert result["actual_api_service_read"] == "UNVERIFIED" and len(cursor.calls) == 3
    else:
        with pytest.raises((ValueError, TypeError)):
            manifest.verify_published(cursor)
        assert len(cursor.calls) == 1


def test_native_capture_rejects_any_retained_january_run_before_acquisition(monkeypatch):
    monkeypatch.setattr(prod, "verify_execution_resource", lambda *args: None)
    cursor = Mock()
    cursor.fetchone.return_value = ("OH_LYME_PROD_PIPELINE_SVC", "OH_LYME_PROD_RUNTIME", prod.PROD)
    cursor.fetchall.return_value = [("a-different-run", "COMPLETED")]
    with pytest.raises(ValueError, match="CLIMATE_PROD_CAPTURE_ALREADY_RETAINED"):
        prod.approved_capture_binding(cursor, "fixture-version", "fixture-decision")
    assert len(cursor.execute.call_args_list) == 2


def test_native_capture_denied_visibility_is_not_absence(monkeypatch):
    monkeypatch.setattr(prod, "verify_execution_resource", lambda *args: None)
    cursor = Mock()
    cursor.fetchone.return_value = ("OH_LYME_PROD_PIPELINE_SVC", "OH_LYME_PROD_RUNTIME", prod.PROD)
    cursor.fetchall.side_effect = RuntimeError("object_or_access_unavailable")
    with pytest.raises(RuntimeError):
        prod.approved_capture_binding(cursor, "fixture-version", "fixture-decision")
