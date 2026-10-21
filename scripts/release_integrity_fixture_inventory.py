"""Run the production release guard inside real fixture-only pointer transactions."""

import copy
import json
import re
import time
from pathlib import Path

from prepare_release_integrity_dev_plan import SCHEMAS
from run_release_integrity_fixture import FROZEN, MARKER, OLD, OLD_BUNDLE

from lyme_gap_atlas_data import release_completeness as gate


def values(items):
    return ",".join("('" + str(item).replace("'", "''") + "')" for item in items)


class RoutedCursor:
    """Real cursor, with the same fixed substitutions as the installed fixture DDL."""

    def __init__(self, fixture, connection):
        self.fixture = fixture
        self.cursor = connection.cursor()

    @property
    def description(self):
        return self.cursor.description

    def execute(self, sql, params=()):
        if time.monotonic() - self.fixture.started > 900:
            raise TimeoutError("RI706_900_SECOND_TOTAL_LIMIT")
        for source, target in SCHEMAS.items():
            sql = re.sub(r"\b" + source + r"\.", target + ".", sql)
        if "ONE_HEALTH_LYME_GAP_ATLAS_PROD" in sql:
            raise ValueError("RI706_PRODUCTION_REFERENCE_FORBIDDEN")
        try:
            self.cursor.execute(sql, params)
        finally:
            self.fixture.receipt["queries"].append(
                {"label": "shared_release_guard", "query_id": self.cursor.sfqid}
            )
            self.fixture.save()

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchmany(self, size):
        return self.cursor.fetchmany(size)

    def fetchall(self):
        return self.cursor.fetchall()


def seed_inventory(f, connection):
    def q(label, sql, params=()):
        return f.query(connection, label, sql, params)

    profile = json.loads(
        (
            Path(__file__).parents[1]
            / "docs/contracts/semantic-release/release-completeness-2026-10-18.json"
        ).read_text()
    )
    sources = sorted(
        gate.REQUIRED
        - {
            "tier1",
            "climate",
            "surveillance-situation-four-state",
            "surveillance-situation-tick-pathogen",
        }
    )
    raw_sources = [
        {
            "source_key": source,
            "source_id": source,
            "dataset_id": source,
            "data_source_version_id": source,
            "ingestion_run_id": source,
            "artifact_id": source,
            "artifact_sha256": "a" * 64,
            "definition_version": 1,
            "field_map": {"fips": ["fips"]},
        }
        for source in sources
    ]
    for release in (OLD, FROZEN):
        q(
            "fixture_nlcd_source",
            "INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES SELECT "
            "%s,'context_nlcd_2025','context_nlcd_2025','context_nlcd_2025','context_nlcd_2025',"
            "'context_nlcd_2025','context_nlcd_2025','context_nlcd_2025','synthetic',"
            "'SYNTHETIC_TEST_NOT_APPROVAL','https://example.invalid/ri706','synthetic' "
            "WHERE NOT EXISTS(SELECT 1 FROM PRESENTATION.SEMANTIC_DATA_SOURCES "
            "WHERE release_id=%s AND source_key='context_nlcd_2025')",
            (release, release),
        )
    q(
        "fixture_nlcd_observations",
        "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS "
        "SELECT r.release_id,c.fips,m.column1,'2025','context_nlcd_2025','context_nlcd_2025',"
        "'context_nlcd_2025','context_nlcd_2025',c.fips,SHA2(c.fips||m.column1,256) "
        "FROM PRESENTATION.SEMANTIC_RELEASES r CROSS JOIN GOVERNANCE.CANONICAL_FIPS c "
        "CROSS JOIN (SELECT column1 FROM VALUES "
        + values(sorted(gate.PRESENTATION_MEASURES["context_nlcd_2025"]))
        + (
            ") m WHERE r.release_id IN (%s,%s) AND c.fips IN ('09110','51013')"
            " AND NOT EXISTS(SELECT 1 FROM PRESENTATION.SEMANTIC_OBSERVATIONS "
            "o WHERE o.release_id=r.release_id AND o.source_key='context_nlcd_"
            "2025' AND o.fips=c.fips AND o.measure_id=m.column1)"
        ),
        (OLD, FROZEN),
    )
    for artifact in profile["artifacts"]:
        artifact["approval_reference"] = MARKER
        if artifact["id"] in sources:
            source = artifact["id"]
            artifact.update({field: source for field in gate.SOURCE_PINS})
            artifact.update(
                label="synthetic",
                vintage="synthetic",
                artifact_sha256="a" * 64,
                source_url="https://example.invalid/ri706",
                note="SYNTHETIC_TEST_NOT_APPROVAL",
                expected_rows=14 if source == "context_nlcd_2025" else 3144,
            )
        if artifact["id"] == "tier1":
            artifact.update(
                compatibility_decision="synthetic-ri706-tier1-a", class_counts={"MEDIUM": 3144}
            )
    for release in (OLD, FROZEN):
        admitted = copy.deepcopy(profile)
        for artifact in admitted["artifacts"]:
            if artifact["id"].startswith("surveillance-situation-"):
                artifact["compatibility_decision"] = "synthetic-old-" + artifact["id"]
        q(
            "fixture_complete_manifest",
            "UPDATE PRESENTATION.SEMANTIC_RELEASES "
            "SET source_manifest=PARSE_JSON(%s) WHERE release_id=%s",
            (json.dumps({"sources": raw_sources, "release_completeness": admitted}), release),
        )
    definitions = {
        "CURRENT_SOURCE_METADATA_V": "SELECT r.release_id AS release_version,s.source_key,"
        "s.source_id,s.dataset_id,s.label,s.vintage,s.source_url,s.note "
        "FROM PRESENTATION.SEMANTIC_DATA_SOURCES s JOIN PRESENTATION.CURRENT_RELEASE_V r "
        "ON s.release_id=r.release_id",
        "CURRENT_COUNTY_ATLAS_V": "SELECT c.* FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS c "
        "JOIN PRESENTATION.CURRENT_RELEASE_V r ON c.release_id=r.release_id",
        "CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V": "SELECT r.release_id AS release_id,"
        "c.fips AS county_fips,m.column1 AS measure_id,DATEADD('day',d.n,DATE '2025-01-01') "
        "AS period_start,DATEADD('day',d.n,DATE '2025-01-01') AS period_end "
        "FROM PRESENTATION.CURRENT_RELEASE_V r CROSS JOIN GOVERNANCE.CANONICAL_FIPS c "
        "CROSS JOIN (SELECT column1 FROM VALUES " + values(sorted(gate.CLIMATE_MEASURES)) + ") m "
        "CROSS JOIN (SELECT ROW_NUMBER() OVER(ORDER BY SEQ4())-1 AS n "
        "FROM TABLE(GENERATOR(ROWCOUNT=>31))) d",
        "CURRENT_CLIMATE_MEASURE_METADATA_V": "SELECT column1 AS measure_id FROM VALUES "
        + values(sorted(gate.CLIMATE_MEASURES)),
    }
    delivered = []
    for source, measures in gate.PRESENTATION_MEASURES.items():
        delivered.append(
            "SELECT r.release_id AS release_version,'" + source + "' AS source_key,"
            "m.column1 AS measure_id,c.fips AS county_fips FROM PRESENTATION.CURRENT_RELEASE_V r "
            "CROSS JOIN GOVERNANCE.CANONICAL_FIPS c CROSS JOIN (SELECT column1 FROM VALUES "
            + values(sorted(measures))
            + ") m"
            + (" WHERE c.fips IN ('09110','51013')" if source == "context_nlcd_2025" else "")
        )
    definitions["CURRENT_COUNTY_OBSERVATIONS_V"] = " UNION ALL ".join(delivered)
    for consumer in profile["independent_consumers"]:
        view = consumer["view"]
        column = gate.INDEPENDENT[view]
        definitions[view] = (
            ("SELECT column1 AS " + column + " FROM VALUES " + values(consumer["expected_keys"]))
            if column
            else ("SELECT NULL::VARCHAR AS item_id WHERE FALSE")
        )
    for view, sql in definitions.items():
        q("fixture_inventory_view", "CREATE OR REPLACE VIEW PRESENTATION." + view + " AS " + sql)
    for view in gate.VIEWS:
        q(
            "fixture_reader_contract_grant",
            "GRANT SELECT ON VIEW PRESENTATION." + view + " TO ROLE OH_LYME_DEV_READ",
        )
    connection.commit()
    return definitions


def run_inventory_matrix(f, migration, owner):
    definitions = seed_inventory(f, migration)

    def q(label, sql, params=()):
        return f.query(migration, label, sql, params)

    for model in ("surveillance-situation-four-state", "surveillance-situation-tick-pathogen"):
        f.query(
            owner,
            "synthetic_rollback_compatibility",
            "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
            (model, OLD, OLD_BUNDLE, "synthetic-old-" + model, MARKER),
        )
        f.query(
            owner,
            "synthetic_duplicate_rollback_compatibility",
            "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
            (model, OLD, OLD_BUNDLE, "synthetic-old-duplicate-" + model, MARKER),
        )

    def transaction(target, failure=False):
        before = q(
            "fixture_pointer_before",
            "SELECT current_release_id FROM PRESENTATION.SEMANTIC_RELEASE_POINTER",
        )
        cursor = RoutedCursor(f, migration)
        q("fixture_begin", "BEGIN")
        try:
            expected = gate.verify_candidate(cursor, target)
            q(
                "fixture_tentative_pointer",
                "UPDATE PRESENTATION.SEMANTIC_RELEASE_POINTER SET current_release_id=%s",
                (target,),
            )
            gate.verify_current(cursor, target, expected, read_role="OH_LYME_DEV_READ")
            if failure:
                raise AssertionError("RI706_EXPECTED_RELEASE_GUARD_FAILURE")
            q("fixture_commit", "COMMIT")
        except gate.ReleaseCompletenessBlocked:
            q("fixture_rollback", "ROLLBACK")
            if not failure:
                raise
            after = q(
                "fixture_pointer_after",
                "SELECT current_release_id FROM PRESENTATION.SEMANTIC_RELEASE_POINTER",
            )
            if after != before:
                raise AssertionError("RI706_RELEASE_GUARD_ROLLBACK_FAILED") from None
        except Exception:
            q("fixture_rollback_unexpected", "ROLLBACK")
            raise
        finally:
            cursor.cursor.close()

    transaction(OLD)
    transaction(FROZEN)
    f.receipt["cases"].append({"case": "complete_inventory_publish_and_rollback", "status": "PASS"})
    for view, broken in (
        (
            "CURRENT_COUNTY_ATLAS_V",
            "SELECT * FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id='" + FROZEN + "'",
        ),
        (
            "CURRENT_SOURCE_METADATA_V",
            definitions["CURRENT_SOURCE_METADATA_V"].replace(
                "s.source_id,", "'incorrect-source' AS source_id,"
            ),
        ),
        (
            "CURRENT_COUNTY_OBSERVATIONS_V",
            definitions["CURRENT_COUNTY_OBSERVATIONS_V"].replace(
                "r.release_id AS release_version", "'wrong-release' AS release_version"
            ),
        ),
        (
            "CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V",
            definitions["CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V"].replace(
                "r.release_id AS release_id", "'wrong-release' AS release_id"
            ),
        ),
    ):
        try:
            q(
                "fixture_wrong_identity_view",
                "CREATE OR REPLACE VIEW PRESENTATION." + view + " COPY GRANTS AS " + broken,
            )
            transaction(OLD, failure=True)
            f.receipt["cases"].append(
                {"case": "reject_same_count_wrong_identity_" + view, "status": "PASS"}
            )
        finally:
            q(
                "fixture_restore_identity_view",
                "CREATE OR REPLACE VIEW PRESENTATION."
                + view
                + " COPY GRANTS AS "
                + definitions[view],
            )
    # Every inventory member is mandatory, even if county/model totals stay unchanged.
    cursor = RoutedCursor(f, migration)
    try:
        for missing in sorted(gate.REQUIRED):
            q("fixture_omission_begin", "BEGIN")
            raw = q(
                "fixture_manifest_read",
                "SELECT source_manifest FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=%s",
                (FROZEN,),
            )[0][0]
            raw = json.loads(raw) if isinstance(raw, str) else raw
            raw["release_completeness"]["artifacts"] = [
                a for a in raw["release_completeness"]["artifacts"] if a["id"] != missing
            ]
            q(
                "fixture_omitted_artifact",
                (
                    "UPDATE PRESENTATION.SEMANTIC_RELEASES SET source_manifest=PARSE_J"
                    "SON(%s) WHERE release_id=%s"
                ),
                (json.dumps(raw), FROZEN),
            )
            try:
                gate.verify_candidate(cursor, FROZEN)
            except gate.ReleaseCompletenessBlocked:
                f.receipt["cases"].append({"case": "reject_omitted_" + missing, "status": "PASS"})
            else:
                raise AssertionError("RI706_OMITTED_REQUIRED_ARTIFACT_ACCEPTED")
            finally:
                q("fixture_omission_rollback", "ROLLBACK")
    finally:
        cursor.cursor.close()
    f.receipt["inventory_scope"] = "SYNTHETIC_ALL_REQUIRED_ARTIFACTS_NOT_PROD_ACCEPTANCE"
    f.save()
