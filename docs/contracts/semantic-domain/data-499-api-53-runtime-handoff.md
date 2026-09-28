# Data #499: API #53 runtime metadata handoff

Status: source reviewed; deployment and API-role query proof pending. This is a
consumer-safe Data publication contract, not an approved public HTTP shape.

## Source and binding

Use `ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.CURRENT_INDICATOR_METADATA_V`
and `ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.CURRENT_MEASURE_METADATA_V`.
The corresponding DEV objects use `ONE_HEALTH_LYME_GAP_ATLAS_DEV`. V123 creates
the views from the immutable V071 release hierarchy. Both join the single
`ATLAS` current pointer to a `PUBLISHED` release. Candidate or failed release
rows cannot appear without a reviewed pointer transition. Rollback changes
both views together by changing that pointer. No observation scan is involved.

The production API configuration names `OH_LYME_PROD_READ`. V123 grants that
role `SELECT` on these two views only; it requires existing database/schema
`USAGE`. DEV uses `OH_LYME_DEV_READ`. This migration adds no table grants,
write/ownership privileges, or access to arbitrary historical releases.
`PRESENTATION.SEMANTIC_*` base tables and source/run/artifact lineage remain
outside this new grant. Existing permissions should be audited separately;
the migration does not revoke earlier grants.

## Fields and meaning

Indicator rows: `indicator_id`, `label`, `description`, `limitation`, `domain`,
`category`, `semantic_contract_version`, `release_version`. Measure membership
is the set of measure rows with matching `indicator_id` and `release_version`.

Measure rows: `measure_id`, `indicator_id`, `label`, `description`,
`measure_type`, `unit`, `denominator`, `geography_type`, `temporal_grain`,
`supported_stratifications`, `source_references`, `standards_mappings`,
`missingness_semantics`, `methodology`, `limitation`,
`semantic_contract_version`, `release_version`.

IDs are stable V071 semantic identity, not labels or warehouse row IDs.
`semantic_contract_version` is the release schema version; `release_version`
is the exact governed release ID. Neither is the #194 consumer serializer
version. The view projections do not independently revise metadata.

The current county release does not persist governed domain/category,
measure definition, denominator, supported strata, source relationship, or
standards mapping on these hierarchy rows. The corresponding columns are
SQL `NULL`; they must not be filled from labels, observation rows, or internal
source artifacts. `geography_type` and `temporal_grain` carry the stored
semantics verbatim, including values such as `COUNTY_FIPS_5`, `STATE`,
`snapshot`, `2023`, or `as published`; they are not normalized capability
lists. `measure_type` is the stored data type, not an invented reported/derived
classification. No clinical integration is implied.

## Filters, ordering, cache, and safety

Exact `indicator_id` and `measure_id` filters are governed. A literal
`geography_type` filter on the stored measure semantics is possible, but it
does not establish observation availability. Domain and category filters are
unsupported because their values are null in this release. Availability has
no governed definition and must not be inferred from row existence. There is
no source, standard, strata, or time-grain capability filter in this contract.

SQL views do not promise row order. API queries should `ORDER BY indicator_id`
or `ORDER BY measure_id`; for relationships, order by `indicator_id, measure_id`.
Results change only when the current pointer moves, but consumers should
include `release_version` in cache identity and revalidate against
`CURRENT_RELEASE_V` after publication or rollback. API #53 owns HTTP TTLs.

V123 explicitly selects safe columns. It excludes credentials, raw payloads,
paths, source record IDs, run/artifact IDs, physical storage identities,
private identifiers, and internal derived-result stores. It does not promote
#158/#159 DEV-only results or assign observation value states.

## Evidence and rollout

Local migration-contract tests prove render/role routing and SQL allowlist
intent only. They do not prove Snowflake object creation, `READ` access, denial
of base tables, or current-pointer contents. Deploy V123 through the normal
checksum-validated DEV migration workflow; prove both SELECTs as
`OH_LYME_DEV_READ`, inspect grants and denied base-table access, then use the
protected PROD promotion path and repeat with the actual API role. Record
release ID/version from both views and `CURRENT_RELEASE_V` before declaring
API #53 unblocked in a live environment. No production data or existing view
definition is changed by V123.
