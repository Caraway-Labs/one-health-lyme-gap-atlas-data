"""Fail-closed consumer reconciliation inside the semantic pointer transaction.

The reviewed candidate manifest is immutable storage, not a CLI override. Human
exceptions require a separately retained human-owner decision. Candidate and
rollback checks use the same boundary; a manifest cannot grant itself an exception.
"""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

SCHEMA = "atlas-release-completeness/v1"
# Discovered from API repository readers, including independently versioned feeds.
VIEWS = (
    "CURRENT_RELEASE_V",
    "CURRENT_SOURCE_METADATA_V",
    "CURRENT_COUNTY_ATLAS_V",
    "CURRENT_COUNTY_OBSERVATIONS_V",
    "CURRENT_INDICATOR_METADATA_V",
    "CURRENT_MEASURE_METADATA_V",
    "CURRENT_METHODOLOGY_METADATA_V",
    "CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V",
    "CURRENT_CLIMATE_MEASURE_METADATA_V",
    "CURRENT_TIER1_COUNTY_REVIEW_V",
    "INTELLIGENCE_FEED_V",
    "INTELLIGENCE_FEED_V2",
    "CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V",
    "COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V",
    "CURRENT_RELEASE_COMPLETENESS_V",
)
REQUIRED = {
    "human",
    "tick",
    "pathogen",
    "context_svi",
    "context_rucc",
    "context_nlcd_2025",
    "climate",
    "tier1",
    "surveillance-situation-four-state",
    "surveillance-situation-tick-pathogen",
}
INDEPENDENT = {
    "INTELLIGENCE_FEED_V": None,
    "INTELLIGENCE_FEED_V2": None,
    "CURRENT_INDICATOR_METADATA_V": "indicator_id",
    "CURRENT_MEASURE_METADATA_V": "measure_id",
    "CURRENT_METHODOLOGY_METADATA_V": "methodology_id",
}
PRESENTATION_MEASURES = {
    "human": {"human_status", "case_count_floor_2023", "incidence_floor_2023"},
    "context_svi": {
        "population_2022",
        "svi_percentile_2022",
        "uninsured_percent_2022",
        "uninsured_percentile_2022",
    },
    "context_rucc": {"rucc_2023"},
    "context_nlcd_2025": {
        "nlcd_forest_area_share_county_year",
        "nlcd_developed_area_share_county_year",
        "nlcd_agriculture_area_share_county_year",
        "nlcd_wetland_area_share_county_year",
        "nlcd_open_water_area_share_county_year",
        "nlcd_mean_impervious_fraction_county_year",
        "nlcd_changed_area_share_county_year",
    },
}
CLIMATE_MEASURES = {
    "nclimgrid_" + name + "_county_day" for name in ("prcp", "tavg", "tmin", "tmax")
}
SOURCE_FIELDS = ("source_id", "dataset_id", "label", "vintage", "source_url", "note")
SOURCE_PINS = ("source_id", "dataset_id", "source_version_id", "ingestion_run_id", "artifact_id")


def verify_source_pins(
    cursor: Any, release_id: str, identity: str, item: dict[str, Any], raw: Any
) -> None:
    """Bind the inventory to retained source rows, manifest bytes and observations."""
    expected = tuple(item.get(f) for f in SOURCE_PINS)
    if not all(isinstance(value, str) and value for value in expected):
        raise ReleaseCompletenessBlocked("Required source lineage pins missing: " + identity)
    cursor.execute(
        "SELECT "
        + ",".join(SOURCE_PINS)
        + " FROM PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=%s AND source_key=%s",
        (release_id, identity),
    )
    if cursor.fetchmany(2) != [expected]:
        raise ReleaseCompletenessBlocked("Retained source lineage differs: " + identity)
    sources = raw.get("sources", []) if isinstance(raw, dict) else []
    matches = [s for s in sources if isinstance(s, dict) and s.get("source_key") == identity]
    if (
        len(matches) != 1
        or any(
            matches[0].get("data_source_version_id" if f == "source_version_id" else f) != value
            for f, value in zip(SOURCE_PINS, expected, strict=True)
        )
        or not item.get("artifact_sha256")
        or matches[0].get("artifact_sha256") != item["artifact_sha256"]
    ):
        raise ReleaseCompletenessBlocked("Immutable source manifest lineage differs: " + identity)
    cursor.execute(
        "SELECT COUNT(*),COUNT_IF(source_version_id=%s AND ingestion_run_id=%s AND artifact_id=%s) "
        "FROM PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id=%s AND source_key=%s",
        (*expected[2:], release_id, identity),
    )
    counts = cursor.fetchone()
    if counts is None or tuple(map(int, counts)) != (item["expected_rows"], item["expected_rows"]):
        raise ReleaseCompletenessBlocked("Observation source lineage differs: " + identity)


def verify_projection_identity(
    cursor: Any, release_id: str, artifacts: dict[str, dict[str, Any]]
) -> None:
    """Check row identities and attribution, including same-count substitutions."""
    canonical = set(
        files("lyme_gap_atlas_data")
        .joinpath("data/canonical-county-fips-2022.txt")
        .read_text()
        .split()
    )
    cursor.execute("SELECT release_id,fips FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V")
    counties = cursor.fetchall()
    if (
        len(counties) != len(canonical)
        or {r[1] for r in counties} != canonical
        or any(r[0] != release_id for r in counties)
    ):
        raise ReleaseCompletenessBlocked("County release identity or canonical membership differs")
    cursor.execute(
        "SELECT release_version,source_key,"
        + ",".join(SOURCE_FIELDS)
        + " FROM PRESENTATION.CURRENT_SOURCE_METADATA_V"
    )
    sources = cursor.fetchall()
    required = {
        key
        for key in REQUIRED
        if key
        not in {
            "tier1",
            "climate",
            "surveillance-situation-four-state",
            "surveillance-situation-tick-pathogen",
        }
    }
    for key in required:
        expected = artifacts[key]
        rows = [r for r in sources if r[1] == key]
        if len(rows) != 1 or rows[0][0] != release_id:
            raise ReleaseCompletenessBlocked("Source release identity missing: " + key)
        for field, actual in zip(SOURCE_FIELDS, rows[0][2:], strict=True):
            if not expected.get(field) or actual != expected[field]:
                raise ReleaseCompletenessBlocked("Source attribution differs: " + key + ":" + field)


def tier1_eligibility_join() -> str:
    """Deduplicate admission identities before joining model rows."""
    return (
        " CROSS JOIN PRESENTATION.CURRENT_RELEASE_V r_current LEFT JOIN "
        "(SELECT DISTINCT artifact_id,batch_id,batch_version,model_version,"
        "input_release_id,input_bundle_sha256,target_release_id,target_bundle_sha256 "
        "FROM PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V) admission ON "
        "admission.artifact_id='tier1' "
        "AND admission.batch_id=v.prediction_batch_version "
        "AND admission.batch_version=v.prediction_batch_version "
        "AND admission.model_version=v.model_version "
        "AND admission.input_release_id=v.release_id "
        "AND admission.input_bundle_sha256=v.bundle_sha256 "
        "AND admission.target_release_id=r_current.release_id "
        "AND admission.target_bundle_sha256=r_current.bundle_sha256"
    )


class ReleaseCompletenessBlocked(ValueError):
    """A required consumer is absent, incompatible or lacks reviewed evidence."""


def validate_manifest(document: Any) -> dict[str, dict[str, Any]]:
    """Reject omissions, duplicates, self-declared exclusions and unbound models."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ReleaseCompletenessBlocked("Required versioned release completeness manifest missing")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReleaseCompletenessBlocked("Completeness artifacts must be a list")
    result = {}
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ReleaseCompletenessBlocked("Invalid artifact identity")
        identity = item["id"]
        if identity in result:
            raise ReleaseCompletenessBlocked("Duplicate completeness artifact")
        if item.get("disposition") not in {"carry_forward", "regenerated", "excluded", "degraded"}:
            raise ReleaseCompletenessBlocked(
                "Excluded/degraded artifacts require a retained owner decision"
            )
        exception = item["disposition"] in {"excluded", "degraded"}
        if exception and not item.get("exception_decision"):
            raise ReleaseCompletenessBlocked(
                "Excluded/degraded artifacts require a retained owner decision"
            )
        for field in ("owner", "consumer", "contract", "scope", "lineage", "approval_reference"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ReleaseCompletenessBlocked("Artifact evidence incomplete: " + identity)
        if type(item.get("expected_rows")) is not int or item["expected_rows"] < (
            0 if exception else 1
        ):
            raise ReleaseCompletenessBlocked("Artifact coverage missing: " + identity)
        if identity in REQUIRED - {
            "tier1",
            "climate",
            "surveillance-situation-four-state",
            "surveillance-situation-tick-pathogen",
        } and any(not isinstance(item.get(f), str) or not item[f].strip() for f in SOURCE_FIELDS):
            raise ReleaseCompletenessBlocked("Required source attribution missing: " + identity)
        if identity in PRESENTATION_MEASURES and (
            not isinstance(item.get("presentation_measures"), list)
            or (
                not exception
                and not PRESENTATION_MEASURES[identity] <= set(item["presentation_measures"])
            )
            or type(item.get("presentation_counties")) is not int
        ):
            raise ReleaseCompletenessBlocked("Presentation measure footprint missing: " + identity)
        if identity == "climate" and (
            not isinstance(item.get("measures"), list)
            or (not exception and not set(item["measures"]) >= CLIMATE_MEASURES)
        ):
            raise ReleaseCompletenessBlocked("Climate measure footprint missing")
        if identity in {
            "tier1",
            "surveillance-situation-four-state",
            "surveillance-situation-tick-pathogen",
        }:
            for field in (
                "batch_id",
                "batch_version",
                "model_version",
                "input_release_id",
                "input_bundle_sha256",
                "compatibility_decision",
            ):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ReleaseCompletenessBlocked(
                        "Model compatibility evidence missing: " + identity
                    )
        result[identity] = item
    if not result.keys() >= REQUIRED:
        raise ReleaseCompletenessBlocked(
            "Required artifact omitted: " + ",".join(sorted(REQUIRED - result.keys()))
        )
    if set(document.get("views", [])) != set(VIEWS):
        raise ReleaseCompletenessBlocked("Consumer view inventory incomplete")
    independent = document.get("independent_consumers", [])
    if not isinstance(independent, list) or len(independent) != len(INDEPENDENT):
        raise ReleaseCompletenessBlocked("Independent consumer inventory incomplete")
    if {i.get("view") for i in independent if isinstance(i, dict)} != set(INDEPENDENT):
        raise ReleaseCompletenessBlocked("Independent consumer inventory incomplete")
    for item in independent:
        for field in ("owner", "consumer", "contract", "scope", "lineage"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ReleaseCompletenessBlocked("Independent consumer evidence missing")
        if type(item.get("minimum_rows")) is not int or item["minimum_rows"] < 0:
            raise ReleaseCompletenessBlocked("Independent coverage policy missing")
        if INDEPENDENT[item["view"]] and not item.get("expected_keys"):
            raise ReleaseCompletenessBlocked("Required metadata identities missing")
    return result


def authorize_artifacts(
    cursor: Any, release_id: str, bundle_sha256: str, artifacts: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Verify retained human decisions using READ-accessible projections only."""
    artifacts = {identity: dict(item) for identity, item in artifacts.items()}
    for identity, item in artifacts.items():
        if item["disposition"] in {"excluded", "degraded"}:
            cursor.execute(
                "SELECT COUNT(*) FROM PRESENTATION.RELEASE_COMPLETENESS_EXCEPTIONS_V "
                "WHERE decision_id=%s AND target_release_id=%s AND target_bundle_sha256=%s "
                "AND artifact_id=%s AND expected_rows=%s",
                (
                    item["exception_decision"],
                    release_id,
                    bundle_sha256,
                    identity,
                    item["expected_rows"],
                ),
            )
            decision = cursor.fetchone()
            if decision is None or int(decision[0]) != 1:
                raise ReleaseCompletenessBlocked("Retained owner exception missing: " + identity)
            continue
        if identity in {
            "tier1",
            "surveillance-situation-four-state",
            "surveillance-situation-tick-pathogen",
        }:
            # Avoid a circular content hash when a regenerated model is fitted
            # to this candidate. This token binds only to the persisted digest;
            # post-pointer validation still requires the real output identity.
            if (
                item["input_release_id"] == release_id
                and item["input_bundle_sha256"] == "TARGET_BUNDLE"
            ):
                item["input_bundle_sha256"] = bundle_sha256
            if (item["input_release_id"], item["input_bundle_sha256"]) != (
                release_id,
                bundle_sha256,
            ):
                cursor.execute(
                    "SELECT COUNT(*) FROM PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V "
                    "WHERE decision_id=%s AND artifact_id=%s AND batch_id=%s "
                    "AND model_version=%s AND batch_version=%s "
                    "AND input_release_id=%s AND input_bundle_sha256=%s "
                    "AND target_release_id=%s AND target_bundle_sha256=%s",
                    (
                        item["compatibility_decision"],
                        identity,
                        item["batch_id"],
                        item["model_version"],
                        item["batch_version"],
                        item["input_release_id"],
                        item["input_bundle_sha256"],
                        release_id,
                        bundle_sha256,
                    ),
                )
                match = cursor.fetchone()
                if match is None or int(match[0]) != 1:
                    raise ReleaseCompletenessBlocked(
                        "Historical model requires approved compatibility admission: " + identity
                    )
    return artifacts


def verify_candidate(cursor: Any, release_id: str) -> dict[str, Any]:
    """Before pointer DML: check immutable source manifest and full source coverage.

    Model compatibility must be an approved exact release/bundle pair. Historical
    input reuse is deliberately blocked until a separately reviewed admission is
    installed; an approval_reference string is never treated as that authority.
    """
    cursor.execute(
        "SELECT source_manifest, bundle_sha256 FROM PRESENTATION.SEMANTIC_RELEASES "
        "WHERE release_id=%s",
        (release_id,),
    )
    rows = cursor.fetchmany(2)
    if len(rows) != 1:
        raise ReleaseCompletenessBlocked("Ambiguous release identity")
    raw = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
    manifest = raw.get("release_completeness") if isinstance(raw, dict) else None
    if manifest is None:
        cursor.execute(
            "SELECT manifest_json FROM PRESENTATION.RELEASE_COMPLETENESS_ADMISSIONS_V "
            "WHERE release_id=%s AND bundle_sha256=%s",
            (release_id, rows[0][1]),
        )
        admissions = cursor.fetchmany(2)
        if len(admissions) == 1:
            value = admissions[0][0]
            manifest = json.loads(value) if isinstance(value, str) else value
    manifest_digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifacts = validate_manifest(manifest)
    assert isinstance(manifest, dict)  # validate_manifest has already enforced this.
    artifacts = authorize_artifacts(cursor, release_id, rows[0][1], artifacts)
    for identity, item in artifacts.items():
        if item["disposition"] in {"excluded", "degraded"}:
            continue
        if identity not in {
            "tier1",
            "surveillance-situation-four-state",
            "surveillance-situation-tick-pathogen",
            "climate",
        }:
            verify_source_pins(cursor, release_id, identity, item, raw)
    return {
        "schema": SCHEMA,
        "bundle_sha256": rows[0][1],
        "manifest_sha256": manifest_digest,
        "artifacts": artifacts,
        "independent_consumers": manifest["independent_consumers"],
    }


def verify_current(cursor: Any, release_id: str, receipt: dict[str, Any]) -> None:
    """After tentative pointer movement, before COMMIT: prove actual projections.

    Any error rolls back the original caller transaction. This catches views pinned
    to an old release, missing view dependencies and disappearing model batches.
    The service-identity post-deployment canary is an additional required gate.
    """
    for view in VIEWS:
        cursor.execute("SELECT * FROM PRESENTATION." + view + " LIMIT 0")
        cursor.execute("SHOW GRANTS ON VIEW PRESENTATION." + view)
        names = [str(c[0]).lower() for c in cursor.description]
        grants = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        if not any(
            g.get("privilege") == "SELECT" and g.get("grantee_name") == "OH_LYME_PROD_READ"
            for g in grants
        ):
            raise ReleaseCompletenessBlocked("API read grant missing: " + view)
    cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V")
    if cursor.fetchmany(2) != [(release_id, receipt["bundle_sha256"])]:
        raise ReleaseCompletenessBlocked("Current release pointer is not unique or differs")
    artifacts = receipt["artifacts"]
    verify_projection_identity(cursor, release_id, artifacts)
    for item in receipt["independent_consumers"]:
        view = item["view"]
        column = INDEPENDENT[view]
        if column:
            cursor.execute("SELECT " + column + " FROM PRESENTATION." + view)
            values = [str(row[0]) for row in cursor.fetchall()]
            if len(values) != len(set(values)) or not set(item["expected_keys"]) <= set(values):
                raise ReleaseCompletenessBlocked("Required metadata disappeared: " + view)
        else:
            cursor.execute("SELECT COUNT(*) FROM PRESENTATION." + view)
            if int(cursor.fetchone()[0]) < item["minimum_rows"]:
                raise ReleaseCompletenessBlocked("Independent coverage decreased: " + view)
    probes = {
        "tier1": ("CURRENT_TIER1_COUNTY_REVIEW_V", "prediction_batch_version"),
        "surveillance-situation-four-state": (
            "CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V",
            "batch_id",
        ),
        "surveillance-situation-tick-pathogen": (
            "CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V",
            "batch_id",
        ),
    }
    for identity, (view, batch_column) in probes.items():
        item = artifacts[identity]
        model_filter = " AND v.model_version=%s"
        expected_release = item["input_release_id"] if identity == "tier1" else release_id
        params: tuple[Any, ...] = (item["batch_id"], expected_release, item["model_version"])
        if identity != "tier1":
            model_filter += " AND v.model_id=%s AND v.batch_version=%s"
            params += (identity, item["batch_version"])
        if identity == "tier1":
            model_filter += (
                " AND ((v.release_id=r_current.release_id "
                "AND v.bundle_sha256=r_current.bundle_sha256) "
                "OR admission.artifact_id IS NOT NULL)"
            )
        joins = ""
        if identity == "tier1":
            joins = tier1_eligibility_join()
        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT county_fips) FROM PRESENTATION."
            + view
            + " AS v"
            + joins
            + " WHERE v."
            + batch_column
            + "=%s AND v.release_id=%s"
            + model_filter,
            params,
        )
        counts = cursor.fetchone()
        if counts is None or tuple(map(int, counts)) != (
            item["expected_rows"],
            item["expected_rows"],
        ):
            raise ReleaseCompletenessBlocked("Required model becomes unavailable: " + identity)
        class_column = "priority_tier" if identity == "tier1" else "class_id"
        cursor.execute(
            "SELECT "
            + class_column
            + ",COUNT(*) FROM PRESENTATION."
            + view
            + " AS v"
            + joins
            + " WHERE v."
            + batch_column
            + "=%s AND v.release_id=%s"
            + model_filter
            + " GROUP BY "
            + class_column,
            params,
        )
        if dict(cursor.fetchall()) != item.get("class_counts"):
            raise ReleaseCompletenessBlocked("Model class distribution changed: " + identity)
    climate = artifacts["climate"]
    cursor.execute(
        "SELECT measure_id,COUNT(*),COUNT(DISTINCT county_fips),"
        "COUNT(DISTINCT county_fips || '|' || TO_VARCHAR(period_start)),"
        "TO_CHAR(MIN(period_start),'YYYY-MM-DD'),TO_CHAR(MAX(period_end),'YYYY-MM-DD') "
        "FROM PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V GROUP BY measure_id"
    )
    climate_rows = cursor.fetchall()
    if sum(int(r[1]) for r in climate_rows) != climate["expected_rows"]:
        raise ReleaseCompletenessBlocked("Climate consumer coverage changed")
    if climate["expected_rows"]:
        if {r[0] for r in climate_rows} != set(climate["measures"]):
            raise ReleaseCompletenessBlocked("Climate measure disappeared")
        expected = (
            climate["rows_per_measure"],
            climate["counties_per_measure"],
            climate["rows_per_measure"],
            climate["period_start"],
            climate["period_end"],
        )
        if any(tuple(r[1:]) != expected for r in climate_rows):
            raise ReleaseCompletenessBlocked("Climate county/day coverage changed")
    cursor.execute("SELECT measure_id FROM PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V")
    if not set(climate["measures"]) <= {r[0] for r in cursor.fetchall()}:
        raise ReleaseCompletenessBlocked("Climate metadata disappeared")
    cursor.execute(
        "SELECT source_key,measure_id,COUNT(*),COUNT(DISTINCT county_fips),"
        "COUNT_IF(source_key='context_nlcd_2025' AND county_fips NOT IN ('09110','51013')) "
        "FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V GROUP BY source_key,measure_id"
    )
    delivered = cursor.fetchall()
    for identity in PRESENTATION_MEASURES:
        item = artifacts[identity]
        rows = [r for r in delivered if r[0] == identity]
        if sum(int(r[2]) for r in rows) != item["presentation_rows"]:
            raise ReleaseCompletenessBlocked("Presentation source becomes unavailable: " + identity)
        if item["presentation_rows"] and (
            {r[1] for r in rows} != set(item["presentation_measures"])
            or any(
                (r[2], r[3], r[4])
                != (item["presentation_counties"], item["presentation_counties"], 0)
                for r in rows
            )
        ):
            raise ReleaseCompletenessBlocked(
                "Presentation measure/county footprint changed: " + identity
            )
