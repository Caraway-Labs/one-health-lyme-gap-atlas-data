"""Fixed CDC source admission and matching expiry; no provider or warehouse calls."""

import hashlib
import importlib.util
import json
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from semantic_contracts import selection_source_ids

from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    ENDPOINTS,
    PROD_SOURCE_DEFINITIONS,
    PROD_SOURCE_SHA256,
)
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.intelligence_items import canonical_json, identity_hash
from lyme_gap_atlas_data.intelligence_metadata import NativeMetadataPolicy
from lyme_gap_atlas_data.intelligence_raw_cleanup import load_exact_plan
from lyme_gap_atlas_data.intelligence_retention import (
    PROD_METADATA_FEED_IDS,
    CleanupPlan,
    RawCopy,
    capture_lease,
    cleanup_due_at,
)
from lyme_gap_atlas_data.migrations import (
    PROD_DATABASE,
    PROD_FEED_EXPANSION_CLEANUP_MIGRATION,
    is_intelligence_prerequisite_batch,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "approved_cdc_registration", ROOT / "scripts/register_eid_expedited_dev.py"
)
assert spec and spec.loader
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)


@pytest.mark.parametrize("source_id", sorted(PROD_METADATA_FEED_IDS))
def test_exact_source_receipt_and_definition_preserve_metadata_bounds(source_id: str) -> None:
    source, checksum = registration.reviewed_package(source_id)
    assert checksum == identity_hash(source) == PROD_SOURCE_SHA256[source_id]
    assert source["topics"] == source["geographies"] == []
    assert source["access_use"]["public_excerpt_permitted"] is False
    assert source["access_use"]["excerpt_max_chars"] == 0
    assert source["limits"] == {
        "maximum_bytes": 2097152,
        "timeout_seconds": 30,
        "maximum_items": 250,
        "maximum_redirects": 0,
        "maximum_attempts": 1,
    }
    definition = load_source_definition(ROOT / PROD_SOURCE_DEFINITIONS[source_id])
    assert definition.source_id == source_id
    assert definition.endpoint_template == ENDPOINTS[source_id] == source["fetch_location"]
    receipts = json.loads(registration.RECEIPTS.read_text())["receipts"]
    receipt = next(r for r in receipts if r["source_id"] == source_id)
    document = receipt["native_policy"]
    policy = NativeMetadataPolicy(
        **{
            **document,
            **{
                key: frozenset(document[key])
                for key in ["inventory", "permitted_paths", "required_paths"]
            },
        }
    )
    policy.validate(source)
    assert policy.permitted_paths == frozenset(
        {"feed/language", "feed/link", "feed/title", "item/link", "item/pubDate", "item/title"}
    )
    fixture = json.loads(
        (ROOT / f"tests/fixtures/intelligence/native-captures/{source_id}.json").read_text()
    )
    assert set(fixture["evidence"]["observed_inventory"]) == policy.inventory


@pytest.mark.parametrize(
    "source_id",
    sorted(selection_source_ids() - set(PROD_SOURCE_SHA256)),
)
def test_unadmitted_sources_cannot_use_the_fixed_registration(source_id: str) -> None:
    with pytest.raises(PermissionError, match="REVIEWED_PACKAGE"):
        registration.reviewed_package(source_id)
    assert source_id not in PROD_SOURCE_DEFINITIONS


def test_nih_news_releases_manual_package_matches_pins() -> None:
    source, checksum = registration.reviewed_package("nih-news-releases", registry_version=1)
    assert checksum == identity_hash(source)
    assert checksum == PROD_SOURCE_SHA256["nih-news-releases"]
    assert source["source_id"] == "nih-news-releases"
    assert source["registry_version"] == 1
    assert source["state"] == "manual"


def test_nih_news_releases_daily_package_matches_pins() -> None:
    source, checksum = registration.reviewed_package("nih-news-releases", registry_version=2)
    assert checksum == identity_hash(source)
    assert source["source_id"] == "nih-news-releases"
    assert source["registry_version"] == 2
    assert source["state"] == "active"


def test_cdc_mmwr_manual_package_matches_pins() -> None:
    source, checksum = registration.reviewed_package("cdc-mmwr", registry_version=1)
    assert checksum == identity_hash(source)
    assert checksum == PROD_SOURCE_SHA256["cdc-mmwr"]
    assert source["source_id"] == "cdc-mmwr"
    assert source["registry_version"] == 1
    assert source["state"] == "manual"


def test_cdc_mmwr_daily_package_matches_pins() -> None:
    source, checksum = registration.reviewed_package("cdc-mmwr", registry_version=2)
    assert checksum == identity_hash(source)
    assert source["source_id"] == "cdc-mmwr"
    assert source["registry_version"] == 2
    assert source["state"] == "active"


@pytest.mark.parametrize("source_id", sorted(PROD_METADATA_FEED_IDS))
def test_new_source_deadline_and_one_source_plan_are_exact(source_id: str, tmp_path: Path) -> None:
    lease = capture_lease(
        source_id=source_id,
        registry_version=1,
        source_sha256=PROD_SOURCE_SHA256[source_id],
        capture_id="offline-expansion-proof",
        artifact_sha256="a" * 64,
        captured_at="2026-10-01T00:00:00Z",
        policy_ref="reviewed-raw30",
        permitted=lambda *_: True,
    )
    assert datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00")) == datetime(
        2026, 10, 31, tzinfo=UTC
    )
    assert cleanup_due_at(lease, "PROD") == datetime(2026, 10, 29, tzinfo=UTC)
    copy = RawCopy(
        "PROD",
        source_id,
        "checkpoint_payload",
        "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_PROD/GOVERNANCE/INGESTION_RUN_PAYLOADS/offline-expansion-proof",
        lease.sha256,
    )
    plan = CleanupPlan("PROD", (source_id,), "2026-10-29T00:00:00Z", (copy,), "b" * 64)
    path = tmp_path / "private-plan.json"
    path.write_text(canonical_json(asdict(plan)))
    assert load_exact_plan(path, plan.sha256, environment="PROD") == plan
    other = next(s for s in PROD_METADATA_FEED_IDS if s != source_id)
    mixed = replace(plan, copies=(replace(copy, source_id=other),))
    path.write_text(canonical_json(asdict(mixed)))
    with pytest.raises(PermissionError, match="PLAN_CHANGED"):
        load_exact_plan(path, mixed.sha256, environment="PROD")


def test_forward_migration_keeps_exact_single_source_and_security_boundaries() -> None:
    migration = next(m for m in load_migrations() if m.version == "V163")
    assert migration.sha256 == PROD_FEED_EXPANSION_CLEANUP_MIGRATION["sha256"]
    assert is_intelligence_prerequisite_batch([PROD_FEED_EXPANSION_CLEANUP_MIGRATION])
    assert "V163" in {m["version"] for m in migration_plan(PROD_DATABASE)}
    sql = migration.source
    body = sql.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
    body_hash = hashlib.sha256(body.strip().encode()).hexdigest()
    assert f"'{body_hash}' AS PROCEDURE_BODY_SHA256" in sql
    assert "ARRAY_SIZE(PARSE_JSON(a.PLAN_CANONICAL_JSON):source_ids)=1" in body
    assert "('cdc-eid-expedited','cdc-eid-ahead-of-print','cdc-outbreaks')" in body
    assert "selected_source_id" in body and "P_COPY_SHA256" in body
    assert "DATEADD(day,30" in body and "DATEADD(hour,48" in body
    assert "CURRENT_TRANSACTION() IS NULL" in body
    assert "a.DOCUMENT:outcome::VARCHAR='pending'" in body
    assert "GRANT USAGE ON PROCEDURE" not in sql
    assert "GRANT OWNERSHIP" not in sql
    assert "DELETE FROM CONFORMED" not in sql


@pytest.mark.parametrize(
    "path,fixed",
    [(p, True) for p in PROD_SOURCE_DEFINITIONS.values()]
    + [
        ("config/sources/cdc_x5j9_wybp.yml", False),
        ("config/sources/intelligence_nih_news_releases.yml", True),
    ],
)
def test_actual_workflow_fixed_source_guard_and_generic_identity_guard_are_complements(
    path: str, fixed: bool
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/run-prod-ingestion.yml").read_text())
    steps = workflow["jobs"]["ingest"]["steps"]
    fixed_step = next(s for s in steps if s.get("name", "").startswith("Require exact reviewed"))
    generic_step = next(
        s for s in steps if s.get("name", "").startswith("Verify protected PROD runtime")
    )

    def applies(expression: str) -> bool:
        pattern = r"inputs\.source_definition\s*(==|!=)\s*'([^']+)'"

        def evaluate_comparison(match: re.Match[str]) -> str:
            equal = path == match[2]
            return str(equal if match[1] == "==" else not equal)

        translated = re.sub(pattern, evaluate_comparison, expression)
        assert re.fullmatch(r"[TrueFals() &|]+", translated)
        return bool(eval(translated.replace("&&", "and").replace("||", "or"), {"__builtins__": {}}))

    assert applies(fixed_step["if"]) is fixed
    assert applies(generic_step["if"]) is not fixed


@pytest.mark.parametrize("handoff_count", [0, 1, 2])
def test_added_source_registration_requires_exact_installed_retention_and_one_handoff(
    handoff_count: int,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "expanded_prod_registration", ROOT / "scripts/register_eid_expedited_prod.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Cursor:
        rows: list[tuple]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, sql, params=()):
            assert sql.startswith("SELECT ")  # Read-only preflight before registry writes.
            if "CURRENT_USER" in sql:
                self.rows = [module.IDENTITY]
            elif "version='V146'" in sql:
                self.rows = [module.V146]
            elif "version='V163'" in sql:
                m = PROD_FEED_EXPANSION_CLEANUP_MIGRATION
                self.rows = [(m["filename"], m["sha256"])]
            else:
                assert params == (PROD_FEED_EXPANSION_CLEANUP_MIGRATION["sha256"],)
                self.rows = [(handoff_count,)]

        def fetchall(self):
            return self.rows

    class Connection:
        def cursor(self):
            return Cursor()

    if handoff_count == 1:
        module.verify_schema(Connection(), "cdc-eid-ahead-of-print")
    else:
        with pytest.raises(PermissionError, match="RETENTION_HANDOFF_REQUIRED"):
            module.verify_schema(Connection(), "cdc-eid-ahead-of-print")
