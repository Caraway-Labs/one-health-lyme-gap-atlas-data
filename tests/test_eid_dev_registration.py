"""Credential-free checks for the one-source governed DEV registration path."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from semantic_contracts import trigger_map

from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_SHA256,
)

spec = importlib.util.spec_from_file_location(
    "eid_registration", Path(__file__).parents[1] / "scripts/register_eid_expedited_dev.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Cursor:
    def __init__(
        self, *, identity: tuple[str, ...] = module.IDENTITY, existing: list[Any] | None = None
    ):
        self.identity = identity
        self.existing = existing or []
        self.statements: list[str] = []
        self.rowcount = 0
        self.rows: list[Any] = []

    def __enter__(self):
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.statements.append(sql)
        if sql.startswith("SELECT CURRENT_USER()"):
            self.rows = [self.identity]
        elif sql.startswith("SELECT registry_version"):
            assert params == (module.SOURCE_ID,)
            self.rows = self.existing
        elif sql.startswith("UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD"):
            self.rowcount = 1
        elif sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS"):
            assert params[:2] == (module.SOURCE_ID, 1)
            assert json.loads(params[3])["source_id"] == module.SOURCE_ID
            self.rowcount = 1

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, cursor: Cursor):
        self.selected = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.selected

    def autocommit(self, enabled: bool) -> None:
        assert enabled is False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_exact_checked_in_document_and_receipt_are_bound() -> None:
    source, checksum = module.reviewed_package()
    assert source["registry_version"] == 1
    assert source["approval"]["decision_ref"] == module.DECISION_REF
    assert checksum == "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4"


def test_wrong_identity_stops_before_any_mutation() -> None:
    source, checksum = module.reviewed_package()
    cursor = Cursor(identity=("OTHER", *module.IDENTITY[1:]))
    connection = Connection(cursor)
    with pytest.raises(PermissionError, match="IDENTITY_REQUIRED"):
        module.register(connection, source, checksum)
    assert cursor.statements == [
        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
    ]
    assert connection.commits == 0


def test_exact_single_insert_and_idempotent_retry() -> None:
    source, checksum = module.reviewed_package()
    first = Connection(Cursor())
    assert module.register(first, source, checksum) == "RECORDED"
    assert first.commits == 1
    assert (
        sum(
            "INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS" in sql
            for sql in first.selected.statements
        )
        == 1
    )
    retry = Connection(Cursor(existing=[(1, checksum, json.dumps(source))]))
    assert module.register(retry, source, checksum) == "ALREADY_RECORDED"
    assert retry.commits == 0 and retry.rollbacks == 1
    assert all("INSERT INTO" not in sql for sql in retry.selected.statements)


def test_different_existing_registry_row_fails_closed() -> None:
    source, checksum = module.reviewed_package()
    connection = Connection(Cursor(existing=[(2, "0" * 64, json.dumps(source))]))
    with pytest.raises(PermissionError, match="REGISTRY_STATE_CHANGED"):
        module.register(connection, source, checksum)
    assert connection.rollbacks == 1 and connection.commits == 0
    assert all("INSERT INTO" not in sql for sql in connection.selected.statements)


def test_mutated_receipt_rejected_before_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = json.loads(module.RECEIPTS.read_text())
    receipt["receipts"][0]["source_sha256"] = "0" * 64
    changed = tmp_path / "receipt.json"
    changed.write_text(json.dumps(receipt))
    monkeypatch.setattr(module, "RECEIPTS", changed)
    with pytest.raises(PermissionError, match="PACKAGE_MISMATCH"):
        module.reviewed_package()


def test_workflow_fixed_registration_exits_before_migration_path() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    start = workflow.index('if [ "$REGISTER_EID_EXPEDITED_DEV" = "true" ]')
    end = workflow.index("exit 0", start)
    branch = workflow[start:end]
    assert "test \"$EXPECTED_PENDING_JSON\" = '[]'" in branch
    assert 'test "$GITHUB_SHA" = "$REVIEWED_COMMIT"' in branch
    assert 'test "$FEED_PREFLIGHT_ACCOUNTING_CONFIRMED" = "true"' in branch
    assert "scripts/register_eid_expedited_dev.py" in branch
    assert workflow.index("apply-reviewed-dev-migrations") > end
    assert "-q " not in branch and "--query" not in branch


PUBMED_SOURCE_IDS = ("pubmed-tick-borne", "pubmed-lyme-borrelia")
ROOT = Path(__file__).parents[1]
FIVE_V1_PINS = {
    "cdc-eid-expedited": "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4",
    "cdc-eid-ahead-of-print": "b92e97c9e958c270645c9710118b3a3076228c6bcb2390b5c58cff9bacb2a7be",
    "cdc-outbreaks": "54793f2c4856602bf8901d09972a44d2a7479056e71eac75ddc88db060646172",
    "nih-news-releases": "38d7364d5ce7b730d16e07197d0bb1cf88403eae59defc66de05e3a3df825bea",
    "cdc-mmwr": "875b0bc1b33f2c89ff4596532ccd8504dc6ce60086f8bba9146183da2b2d59a6",
}
FIVE_V2_PINS = {
    "cdc-eid-expedited": "570a796df7086b520136e5deab5917957561314e2f5fe96659bb3c9534124423",
    "cdc-eid-ahead-of-print": "12e3003da3e8782b379e321eb61fccecb36a9269c3017c10132bb96c848c39c3",
    "cdc-outbreaks": "d8bdcc90b16c98fe2b3661a9316ac78071bd355cbb46ee5d0299c15ca4f53b8f",
    "nih-news-releases": "1542aa4d8f85a650ac216e574907ec19f65e1d17a26dd8c8b607bfdcd17faaa1",
    "cdc-mmwr": "9ee7ceca898a4419241d9706c7cbf0a795287c794cdeb74b0892a4f90ccda0e9",
}


def _workflow_inputs(name: str) -> dict[str, Any]:
    document = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    return trigger_map(document)["workflow_dispatch"]["inputs"]


def _registration_branch() -> str:
    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    start = workflow.index('if [ "$REGISTER_EID_EXPEDITED_DEV" = "true" ]')
    return workflow[start : workflow.index("exit 0", start)]


def _case_block(branch: str, variable: str) -> str:
    marker = f'case "${variable}" in'
    start = branch.index(marker)
    return branch[start : branch.index("esac", start) + len("esac")]


def _run_case(snippet: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", snippet],
        env=os.environ | env,
        capture_output=True,
        text=True,
        check=False,
    )


def _fixture_source(source_id: str, registry_version: int) -> dict[str, Any]:
    source = json.loads((ROOT / "config/intelligence/cdc-eid-expedited-source-v1.json").read_text())
    source["source_id"] = source_id
    source["registry_version"] = registry_version
    source["family"] = "pubmed"
    return source


def _write_fixture(root: Path, source: dict[str, Any]) -> None:
    directory = root / "config/intelligence"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{source['source_id']}-source-v{source['registry_version']}.json"
    (directory / name).write_text(json.dumps(source), encoding="utf-8")


def _prod_registration():
    spec = importlib.util.spec_from_file_location(
        "eid_prod_registration_lists",
        ROOT / "scripts/register_eid_expedited_prod.py",
    )
    assert spec and spec.loader
    prod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prod)
    return prod


def test_workflows_list_pubmed_ids_and_keep_empty_pending() -> None:
    prod_inputs = _workflow_inputs("register-prod-eid.yml")
    dev_inputs = _workflow_inputs("deploy-dev.yml")
    assert prod_inputs["source_id"]["default"] == "cdc-eid-expedited"
    assert prod_inputs["source_id"]["options"][-2:] == list(PUBMED_SOURCE_IDS)
    assert dev_inputs["intelligence_register_source_id"]["options"][-2:] == list(PUBMED_SOURCE_IDS)
    assert prod_inputs["registry_version"]["options"] == ["1", "2"]
    assert dev_inputs["intelligence_register_registry_version"]["options"] == ["1", "2"]
    prod_text = (ROOT / ".github/workflows/register-prod-eid.yml").read_text()
    assert prod_text.count("guard_eq expected_pending_json '[]'") == 1
    branch = _registration_branch()
    assert "test \"$EXPECTED_PENDING_JSON\" = '[]'" in branch
    source_case = _case_block(branch, "INTELLIGENCE_REGISTER_SOURCE_ID")
    version_case = _case_block(branch, "INTELLIGENCE_REGISTER_REGISTRY_VERSION")
    assert "pubmed-tick-borne|pubmed-lyme-borrelia" in source_case
    assert "1|2)" in version_case
    assert "1|2|3)" not in version_case
    for source_id in (*FIVE_V1_PINS, *PUBMED_SOURCE_IDS):
        accepted = _run_case(source_case, {"INTELLIGENCE_REGISTER_SOURCE_ID": source_id})
        assert accepted.returncode == 0, accepted.stderr
    refused = _run_case(source_case, {"INTELLIGENCE_REGISTER_SOURCE_ID": "pubmed-unknown"})
    assert refused.returncode != 0
    assert "Unsupported intelligence registration source" in refused.stderr
    for version in ("1", "2"):
        accepted = _run_case(version_case, {"INTELLIGENCE_REGISTER_REGISTRY_VERSION": version})
        assert accepted.returncode == 0, accepted.stderr
    for version in ("0", "3", "4"):
        refused = _run_case(version_case, {"INTELLIGENCE_REGISTER_REGISTRY_VERSION": version})
        assert refused.returncode != 0
        assert "Unsupported intelligence registration version" in refused.stderr


def test_existing_five_pins_unchanged_and_real_files_match_when_present() -> None:
    assert PROD_SOURCE_SHA256 == FIVE_V1_PINS
    assert PROD_DAILY_SOURCE_SHA256 == FIVE_V2_PINS
    versions = {1: PROD_SOURCE_SHA256, 2: PROD_DAILY_SOURCE_SHA256}
    for source_id in (*FIVE_V1_PINS, *PUBMED_SOURCE_IDS):
        for version, pins in versions.items():
            path = ROOT / f"config/intelligence/{source_id}-source-v{version}.json"
            if source_id not in pins or not path.is_file():
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            assert module.identity_hash(document) == pins[source_id]
            reviewed, checksum = module.reviewed_package(source_id, version)
            assert checksum == pins[source_id]
            assert reviewed["registry_version"] == version


def test_fixture_pinned_pubmed_ids_pass_reviewed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins: dict[tuple[str, int], str] = {}
    for source_id in PUBMED_SOURCE_IDS:
        document = _fixture_source(source_id, 1)
        pins[(source_id, 1)] = module.identity_hash(document)
        _write_fixture(tmp_path, document)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    def pins_for(registry_version: int) -> dict[str, str]:
        if registry_version == 1:
            return {
                **PROD_SOURCE_SHA256,
                **{source_id: digest for (source_id, _), digest in pins.items()},
            }
        if registry_version == 2:
            return dict(PROD_DAILY_SOURCE_SHA256)
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")

    monkeypatch.setattr(module, "_pins_for_version", pins_for)
    for source_id in PUBMED_SOURCE_IDS:
        reviewed, checksum = module.reviewed_package(source_id, 1)
        assert reviewed["source_id"] == source_id
        assert checksum == pins[(source_id, 1)]


def test_unknown_source_and_other_versions_are_refused_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for source_id, version in (
        ("pubmed-unknown", 1),
        ("pubmed-tick-borne", 3),
        ("cdc-eid-expedited", 3),
        ("pubmed-lyme-borrelia", 4),
    ):
        with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
            module.reviewed_package(source_id, version)
    assert not any(tmp_path.rglob("*.json"))

    class Connection:
        def cursor(self) -> None:
            raise AssertionError("registration wrote before the package check")

    with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
        module.register(
            Connection(),
            {"source_id": "pubmed-unknown", "registry_version": 1},
            "ab" * 32,
        )


def test_changed_pinned_registry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = "pubmed-tick-borne"
    document = _fixture_source(source_id, 1)
    _write_fixture(tmp_path, document)
    real_hash = module.identity_hash(document)

    def lookup(requested_id: str, registry_version: int) -> str:
        if (requested_id, registry_version) == (source_id, 1):
            return "0" * 64
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_pinned_registry_sha256", lookup)
    with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
        module.reviewed_package(source_id, 1)

    prod = _prod_registration()
    monkeypatch.setattr(prod._dev_module, "ROOT", tmp_path)
    monkeypatch.setattr(prod._dev_module, "_pinned_registry_sha256", lookup)
    with pytest.raises(PermissionError, match="EID_PROD_SOURCE_HASH_CHANGED"):
        prod.require_additional_source_hash(source_id, 1)

    def matching(requested_id: str, registry_version: int) -> str:
        if (requested_id, registry_version) == (source_id, 1):
            return real_hash
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")

    monkeypatch.setattr(prod._dev_module, "_pinned_registry_sha256", matching)
    prod.require_additional_source_hash(source_id, 1)
    with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
        prod.require_additional_source_hash("pubmed-unknown", 1)
    prod.require_additional_source_hash("cdc-mmwr", 1)
