"""Frozen handoff integrity and publisher identity checks stay offline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "situations", ROOT / "scripts/publish_surveillance_situations.py"
)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def test_changed_handoff_fails_before_snowflake(tmp_path: Path) -> None:
    first = next(iter(publisher.PINS))
    path = tmp_path / first
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    with pytest.raises(ValueError, match="checksum mismatch"):
        publisher.verify(tmp_path)


def test_human_identity_cannot_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    queries = []

    def query(connection, sql):
        queries.append(sql)
        return [
            {
                "U": "MATTHEWCARAWAY",
                "R": "OH_LYME_PROD_ML_PUBLISHER",
                "D": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                "W": "OH_LYME_PROD_INGEST_XS_WH",
            }
        ]

    monkeypatch.setattr(publisher, "query", query)
    with pytest.raises(ValueError, match="identity"):
        publisher.publish("test", {}, "prod")
    assert len(queries) == 1


def test_pinned_documents_and_migration_digests_agree() -> None:
    sql = (ROOT / "migrations/V158__surveillance_situation_publication.sql").read_text()
    for digest in publisher.PINS.values():
        assert digest in sql
    assert "GRANT SELECT ON TABLE FEATURE_STORE" not in sql
    assert (
        "GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE"
        "(BOOLEAN,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_OWNER" in sql
    )


def test_publisher_cannot_stage_with_only_ml_handoff_approval(monkeypatch):
    calls = []

    def query(connection, sql):
        calls.append(sql)
        return [
            {
                "U": "OH_LYME_PROD_TIER1_ML_PUBLISHER_SVC",
                "R": "OH_LYME_PROD_ML_PUBLISHER",
                "D": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                "W": "OH_LYME_PROD_INGEST_XS_WH",
            }
        ]

    monkeypatch.setattr(publisher, "query", query)
    with pytest.raises(ValueError, match="Data owner publication authorization"):
        publisher.publish("test", {}, "prod")
    assert len(calls) == 1


def test_optional_operator_replay() -> None:
    root = Path("C:/codex_programming/atlas-ml138-handoff")
    if not root.exists():
        pytest.skip("Frozen private county artifact is operator-local")
    assert len(publisher.verify(root)) == 4
