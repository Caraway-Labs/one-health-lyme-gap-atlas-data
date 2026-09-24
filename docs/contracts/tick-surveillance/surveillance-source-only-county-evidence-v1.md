# Source-only county evidence v1

Status: Internal DEV remediation candidate; no public or PROD release
Owner: Atlas data stewardship and engineering
Schema: `surveillance-source-only-county-evidence-v1.schema.json`

This safe envelope retains a source row whose reported geography cannot be
resolved to a canonical county. It links to one `UNKNOWN` #171 result and
records only safe publisher, product, version, vintage, source record/revision,
reported geography/type, unresolved or ambiguous reason, scientific dimension,
normalization references, retrieval time, and evidence basis. Raw source
content, artifact paths, and credentials are excluded. The envelope has no
`county_fips` field and is not a canonical county-status observation.

It cannot establish county completeness, publisher omission,
`NOT_REPORTED_IN_DATASET`, surveillance coverage, county representativeness,
or a #172 county cohort or tie group. Reconciliation to a county would require
a separate reviewed canonical observation; this envelope is never rewritten
into one.
