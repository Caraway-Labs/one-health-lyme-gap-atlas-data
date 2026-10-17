# API #212 county context consumer serving

Status: implementation candidate; protected deployment and reader-role acceptance
are required before declaring the API serving dependency resolved.

## Boundary and admission

V138 intentionally restricts `CURRENT_COUNTY_OBSERVATIONS_V` to annual human
observations and the reviewed NLCD cohort. It cannot admit the SVI ACS period
or RUCC classification vintage by extending its annual allowlist alone.

Forward migration V155 extends that same view. Its original 29 columns and
human/NLCD admission are preserved, with twelve nullable metadata columns
appended. The climate views are untouched. Existing explicit-column API reads
remain compatible. No new table, ingestion, release, source record, pointer,
role, grant, consumer endpoint, or ML admission is introduced.

The context branch requires the current published release
`governed-2026-10-15-january-climate-prod`, bundle
`53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d`,
the exact reviewed source/dataset/resource/version/run/artifact tuples, retained
observation lineage, canonical release county identity, and compatible physical
time, transformation, quality and value state. Duplicate admitted county/measure
rows are excluded rather than arbitrarily selected. Other releases/sources are
unavailable until explicitly reviewed in a forward migration. No fallback to
Alpha, RAW, CONFORMED, or the wide summary view.

The five #191 metadata envelopes reviewed in DATA PR #600 remain unchanged and
`INTERNAL`. V155 publishes only an explicit serving column allowlist with their
revision references, definitions, units, allowed states, and limitations. It
does not reclassify or expose the complete envelopes or private lineage fields.
Owner review of this bounded serving admission is required before merge.

## Measure contract

| Measure | Field | Unit / type | Time | Value states |
|---|---|---|---|---|
| population_2022 | E_TOTPOP | people / integer estimate | ACS 2018-01-01 through 2022-12-31; product vintage 2022 | OBSERVED, ZERO, MISSING |
| svi_percentile_2022 | RPL_THEMES | percentile / number, 0–1 | Same ACS reference period and product vintage | OBSERVED, ZERO, MISSING |
| uninsured_percent_2022 | EP_UNINSUR | percent / number, 0–100 | Same ACS reference period and product vintage | OBSERVED, ZERO, MISSING |
| uninsured_percentile_2022 | EPL_UNINSUR | percentile / number, 0–1 | Same ACS reference period and product vintage | OBSERVED, ZERO, MISSING |
| rucc_2023 | RUCC_2023 | code / categorical integer, 1–9 | VINTAGE_YEAR 2023; null period_start/end | OBSERVED only |

Values and states come from immutable semantic observations; no summary-to-state
inference. The reviewed sources do not admit an UNAVAILABLE physical value state
for these five measures. Unadmitted/missing observations produce no row and must
be reported unavailable by the API, never synthesized as zero. A MISSING SVI row
requires SQL/VARIANT null. RUCC zero, null, fractional and out-of-codebook values
are not admitted. Labels are copied from the frozen DATA #200 2023 codebook.
No category averaging, disease-risk inference, or automatic model admission.

`semantic_contract_version` remains the release schema version. New
`semantic_version` is the measure version (SVI 1.0.0; RUCC 2.0.0), and
`metadata_revision_id` is the exact reviewed #191 revision. The separate
`metadata_methodology_version` is semantic-1.0.0; physical
`transformation_version` remains svi_numeric_projection_v2 or
semantic_county_assembly_v1. Existing observation/release limitations and the
structured `context_limitations` must all be retained. `source_published_at`
stays null; physical observation `retrieved_at` is not a publication date.
`methodology_id` stays null rather than inventing a discoverable resource.

Additional columns: semantic_version, metadata_revision_id,
metadata_methodology_version, vintage_year, value_type, category_label,
source_field, definition, allowed_value_states, context_limitations,
source_published_at, context_contract_version (`atlas-county-context-consumer/1`).

## Current verification evidence

Named PAT `ATLAS_PROD_OWNER`, explicit COMPUTE_WH, verified
MATTHEWCARAWAY / OH_LYME_PROD_OWNER / ONE_HEALTH_LYME_GAP_ATLAS_PROD /
COMPUTE_WH. This is owner-read candidate evidence, not reader/service proof.
Bounded SELECT of the proposed context branch returned all ten expected rows,
query `01c7c81c-030c-43da-0064-2d070128d016`. Final full proposed view SELECT (both legacy UNION branches and the final context guards) returned the same ten observations, query `01c7c81f-030c-442e-0064-2d0701289aae`; stored values are INTEGER for population/RUCC and DECIMAL for SVI/insurance.

| Measure | 01001 | 08001 |
|---|---:|---:|
| population_2022 | 58761 | 520149 |
| svi_percentile_2022 | 0.2663 | 0.7264 |
| uninsured_percent_2022 | 7.4 | 10.8 |
| uninsured_percentile_2022 | 0.412 | 0.6742 |
| rucc_2023 | 2 | 1 |

These match the reader-accessible county summary values recorded in the API
blocker. The candidate also returned genuine ZERO: SVI 49029 and both insurance
measures 48301, query `01c7c81c-030c-442e-0064-2d0701289a9e`.
No current MISSING live sample is claimed. Synthetic tests execute the actual
admission SELECT transpiled to SQLite, testing domain/state, provenance and
release rejection, leading-zero identity, duplicate rejection, all nine labels,
metadata packet parity, and preservation of V138's original definition. SQLite
tests are not Snowflake engine or authorization proof.

## Protected rollout and rollback

The existing promote-prod workflow adds `county_context_only=true` with
`image_digest=county-context-only`, exact green main `reviewed_commit`, and
`expected_pending_json` containing the exact V150/V155 filenames and checksums.
It retains the protected production environment, resource limits and existing
service credentials. One 180-second process deadline plus 15-second termination
grace; no automatic reruns. V150 remains pending and cannot execute in this mode.
Mixed modes, other pending migrations, wrong checksums, release changes or
missing owner access stop execution. No image or job topology promotion.

The deployer service authenticates as its migration role. View replacement uses
the existing OH_LYME_PROD_OWNER role through the canonical migration runner,
matching V138's owner execution; COPY GRANTS preserves OH_LYME_PROD_READ SELECT.
Pre/post gates compare the exact active release, owner/reader grants, 23 legacy
rows for 01001/09110/51013, ten proposed/deployed context rows, and county summary
parity. Missing ability for the protected service to use the existing owner
role is a security-owner blocker; do not add grants or use an administrative
identity to bypass it.

After protected deployment, use the named ATLAS_PROD_READ connection, validate
identity and warehouse first, then perform bounded parameterized reads of the
same ten rows from the actual view. Verify values, states, temporal fields,
metadata, labels, limitations, and existing human/NLCD/climate reads. Retain
query IDs and update API #212. Actual API-service-key and anonymous HTTP
acceptance remain API #212's separate delivery gates.

Rollback is a reviewed new forward migration restoring V138's view projection
and admission. Do not replay/edit V138/V155 or delete migration history. No data
or release rollback is needed. If postapply verification fails, stop; do not
automatically retry, broaden permissions, or mark the dependency resolved.
