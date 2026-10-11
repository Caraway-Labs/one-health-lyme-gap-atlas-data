"""Bounded CDC admission predicates over the existing governed authority snapshot.

No I/O, approval flag, registry service or publication side effect. The authority
snapshot must be assembled from retained governed records by a trusted adapter.
"""

from collections.abc import Mapping
from typing import Any

RELEASE_ID = "governed-2026-09-18-unknown-coverage"
BUNDLE_SHA256 = "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026"
SOURCE_ID = "cdc_arbonet_tick_module"
PERIOD = "2025-12-31"
SLICES = {
    "scapularis_status": {
        "resource_key": "cdc_tick_ixodes_county_status",
        "dataset_id": "cdc-ixodes-county-status-2025",
        "source_version_id": "b81c116f-d93d-4c6b-9d11-ac2477e0e242",
    },
    "burgdorferi_status": {
        "resource_key": "cdc_tick_ixodes_pathogen_status",
        "dataset_id": "cdc-ixodes-pathogen-status-2025",
        "source_version_id": "92b22f19-0d5d-4576-a7c6-6c9af9343edf",
    },
}


def is_cdc_edge(edge: Mapping[str, Any]) -> bool:
    """Only the two exact reviewed source-version tuples can use CDC joins."""
    return (
        edge.get("source_id") == SOURCE_ID
        and edge.get("source_vintage") == "2025"
        and any(
            all(edge.get(field) == value for field, value in scope.items())
            for scope in SLICES.values()
        )
    )


def is_restricted_cdc_source(edge: Mapping[str, Any]) -> bool:
    """Live versions require admission; existing synthetic fixtures stay separate."""
    return (
        edge.get("source_id") == SOURCE_ID
        and not str(edge.get("source_version_id", "")).startswith("fixture-")
        and edge.get("resource_key") in {scope["resource_key"] for scope in SLICES.values()}
    )


def is_cdc_metadata(metadata: Mapping[str, Any]) -> bool:
    measure = metadata.get("measure", {})
    scope = SLICES.get(measure.get("measure_id"))
    if scope is None:
        return False
    provenance = metadata.get("provenance", {})
    return (
        measure.get("origin") == "REPORTED"
        and measure.get("semantic_version") == "1.0.0"
        and measure.get("geography_grain") == "COUNTY"
        and measure.get("temporal_semantics") == "CUMULATIVE_THROUGH_DATE"
        and measure.get("methodology_version") == "tick-surveillance-v1"
        and provenance.get("source_id", {}).get("value") == SOURCE_ID
        and provenance.get("source_vintage", {}).get("value") == "2025"
        and all(
            provenance.get(field, {}).get("value") == scope[field]
            for field in ("dataset_id", "source_version_id")
        )
        and metadata.get("freshness", {}).get("observation_period")
        == {"state": "KNOWN", "value": PERIOD}
    )


def cdc_consumer_admitted(lineage: Mapping[str, Any], authority: Mapping[str, Any]) -> bool:
    """Require reviewed metadata bound by release authority, never caller consent."""
    metadata = lineage.get("metadata", {})
    if (
        not is_cdc_metadata(metadata)
        or metadata.get("visibility") != "CONSUMER_SAFE"
        or metadata.get("steward_review", {}).get("state") != "REVIEWED"
    ):
        return False
    release = lineage.get("release")
    edges = lineage.get("edges", [])
    observation = lineage.get("observation", {})
    if (
        not isinstance(release, Mapping)
        or release.get("release_id") != RELEASE_ID
        or release.get("bundle_sha256") != BUNDLE_SHA256
        or len(edges) != 1
        or not is_cdc_edge(edges[0])
        or observation.get("temporal") != {"semantics": "CUMULATIVE_THROUGH_DATE", "date": PERIOD}
        or observation.get("geography", {}).get("grain") != "COUNTY"
    ):
        return False
    edge = edges[0]
    scope = SLICES[metadata["measure"]["measure_id"]]
    if any(edge.get(field) != value for field, value in scope.items()):
        return False
    membership = authority.get("releases", {}).get(RELEASE_ID, {})
    source = authority.get("source_versions", {}).get(edge["source_version_id"], {})
    if (
        membership.get("bundle_sha256") != BUNDLE_SHA256
        or metadata.get("revision_id") not in membership.get("metadata_revision_ids", [])
        or observation.get("revision_id") not in membership.get("semantic_revision_ids", [])
        or release.get("observation_id") not in membership.get("observation_ids", [])
        or membership.get("observation_records", {}).get(release.get("observation_id"))
        != edge.get("record_id")
        or source.get("approved") is not True
    ):
        return False
    # Existing V087 final-copy attestation rows, not a new approval boolean.
    attestations = membership.get("restricted_source_publication_attestations", [])
    return any(
        isinstance(item, Mapping)
        and item.get("semantic_release_id") == RELEASE_ID
        and item.get("resource_key") == scope["resource_key"]
        and item.get("data_source_version_id") == scope["source_version_id"]
        and isinstance(item.get("attestation_id"), str)
        and bool(item["attestation_id"].strip())
        and isinstance(item.get("attested_by"), str)
        and bool(item["attested_by"].strip())
        and isinstance(item.get("delivery_reference"), str)
        and len(item["delivery_reference"].strip()) >= 6
        and item.get("delivered_at") is not None
        for item in attestations
    )
