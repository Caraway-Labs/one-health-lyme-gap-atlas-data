# DATA #199/#200 metadata and legacy-lineage review handoff

Status: **five source-bound #191 metadata revisions REVIEWED on 2026-10-04; #193 live validation FAIL because the authorized owner role cannot read the historical conformed-record table**. This supplements the [PROD source/record reconciliation](data-199-200-prod-authority-reconciliation-2026-10-03.md). It does not revise the published release or assert a live #193 PASS.

## Current evidence and storage boundary

The 2026-10-04 human-run SELECT-only CSV exports were made as `MATTHEWCARAWAY` / `OH_LYME_PROD_READ` / `ONE_HEALTH_LYME_GAP_ATLAS_PROD` / `COMPUTE_WH`. The CSVs stay with the operator; they are not committed. Local SHA-256 receipts:

| Export | SHA-256 |
| --- | --- |
| `01_session_context.csv` | `7140f47dbee14d5601bfa7e81486018a00a48dd999eace70fd09cdadb4ed842` |
| `02_current_measure_metadata.csv` | `8c0767afafc642e63cc63cfcabe055ba79bdda215444d2feac3eef23e8fd6559` |
| `03_semantic_measure_rows.csv` | `c76fe88d748b3699c1632524e31f95c79464356fa9bac127c9867826e1a9fa0c` |
| `04_metadata_authority_column_inventory.csv` | `a8502e0f2abf47fef564f31e8ea1cd2e9b11cafc78a417e7b44a2886ae3bc467` |
| `05_semantic_governance_objects.csv` | `87b0bba02ea71112dd36fb7715e192cd8ac07a1695978a015a2e18588c516acd` |
| `06_current_release_2026-10-04-0948.csv` | `18e1fc3972b59cac12eb18e357fbd30419b3da6c132d609a68fc578c78e2b75b` |
| `07_semantic_indicators_2026-10-04-0949.csv` | `0a376b66146e8c24eab8f64a52537198cceff4dfd1fbb37917f3b411899d3d58` |

`PRESENTATION.SEMANTIC_RELEASES` reports the pinned release and bundle as `PUBLISHED`, approved by `MATTHEWCARAWAY` on 2026-09-18. Its source manifest contains the exact SVI and RUCC source-version/run/artifact tuples; that release approval is not a #191 metadata-envelope review. `PRESENTATION.SEMANTIC_MEASURES` stores label, data type, unit, geography, temporal resolution, missingness text, methodology and limitation, but no #191 revision, meaning signature, allowed-state list or steward review. Historical builder rows place `population_context`/`rurality_context` in physical `MEASURE_ID` and the five canonical measure IDs in physical `INDICATOR_ID`. Migration V124 corrects that reversal in `CURRENT_MEASURE_METADATA_V`; the view constructs description, denominator, source references and other fields as NULL. Those NULLs do not establish absent scientific meaning. `SEMANTIC_INDICATORS` confirms the two indicator identities.

The supplied column and object inventories show no relation identified as a persisted #191 reviewed-envelope authority. PR #418 and the #191 completion record explicitly made the contract storage-neutral and added no metadata table, writer or migration. `GOVERNANCE.LINEAGE_EDGES` is the generic V001 transformation-edge ledger, not a #191 authority store; catalog, dataset-discovery and intelligence `METADATA_*` fields refer to their own domains. The inventory is not proof that no undiscovered VARIANT could contain a copy, but the reviewed implementation provides no such governed read route. There is no reason to query another object merely to find a presumed table.

## Five review candidates and reviewed packet

The initial packet contained complete PENDING #191 envelopes bound to the exact PROD SVI (`b8b6bf61-c6a3-4538-b0df-1b88c61720b1`) and RUCC (`87872b36-93ab-4a34-b70e-29569192cb48`) source versions. After explicit Atlas product-owner approval under ADR 0035's product/data stewardship decision ownership, the [reviewed JSON packet](data-199-200-metadata-reviewed-2026-10-04.json) records `REVIEWED` and the actual 2026-10-04 review date. Content-derived revision IDs were recomputed and validated; all five retain `INTERNAL` visibility. The four SVI identities remain version `1.0.0`; RUCC uses version `2.0.0` because its temporal meaning changed from a fabricated point date to a source-faithful vintage year.

| Measure | Source field | Proposed meaning and review focus | Actual PROD states in PR #600 |
| --- | --- | --- | --- |
| `population_2022` | SVI `E_TOTPOP` | ACS 2018–2022 county total population estimate; `NONE` ratio denominator | 3,144 OBSERVED |
| `svi_percentile_2022` | SVI `RPL_THEMES` | National county percentile reference, not a person denominator | 3,143 OBSERVED; 1 ZERO |
| `uninsured_percentile_2022` | SVI `EPL_UNINSUR` | National county percentile ranking of `EP_UNINSUR` | 3,143 OBSERVED; 1 ZERO |
| `uninsured_percent_2022` | SVI `EP_UNINSUR` | Percent of civilian noninstitutionalized population, distinct from `E_TOTPOP` | 3,143 OBSERVED; 1 ZERO |
| `rucc_2023` | RUCC `RUCC_2023` | 2023 codes 1–9; category/vintage rather than continuous distance or annual value | 3,144 OBSERVED |

For the four SVI revisions, `OBSERVED`, genuine `ZERO`, and sentinel/null `MISSING` are approved permitted states: the first two are emitted in PROD as above; `MISSING` is the explicit sentinel/null handling in the #199 residual contract, not a current PROD count. RUCC admits `OBSERVED` only because the existing assembler blocks missing, zero and out-of-domain codes. The `GOVERNED_GENERATED` field-authority classification records how the wording was assembled from governed documents; `steward_review.REVIEWED` separately records the owner decision on that wording. The four SVI observation periods are the source-documented ACS 2018-01-01 through 2022-12-31; RUCC carries only `VINTAGE_YEAR: 2023`. Publisher publication dates, exact retrieval timestamps, and uncertainty remain explicitly unknown rather than inferred from release approval.

## Exact #193 legacy boundary

PR #600 proves all 15,720 selected observation links have one historical `CONFORMED.GOVERNED_SOURCE_RECORDS` match by run, source record ID and row hash; V103 capture absence is expected for these runs. That aggregate does not supply the actual five-to-eight example row envelopes required for `validate_lineages()`. The legacy conformed table also has no `record_revision`, `artifact_id`, or `source_version_id` columns. The separately verified release source tuple and artifact ledger bind the latter two. A legacy record revision must be explicitly defined from retained immutable content and reviewed, rather than copied from a nonexistent V103 capture. #190's `POINT_IN_TIME` RUCC candidate likewise requires an exact date while the physical release records only vintage `2023`; assigning January 1 or December 31 would invent time semantics. The steward/release owner must resolve that mapping or approve a versioned contract correction before claiming RUCC #193 PASS. For SVI, any conversion from the ACS 2018–2022 label to exact ISO start/end dates also needs an explicit reviewed mapping. Computed #190 semantic revision membership must be tied one-to-one to the physical release observation IDs; the bundle hash alone does not provide it.

The human-run result of the first example query is `Untitled 27_2026-10-04-1050.csv`, SHA-256 `e4226de0614abd77a9411dbdb506f4f5bc3ccc0ba3ac7341211c445ec7e50703` (operator-held, not committed). It returned the expected eight current-release physical observations: five OBSERVED, one ZERO each for the three SVI/insurance measures, and five exact source-version/run/artifact bindings. All eight `CONFORMED_RECORD_ID` and `SOURCE_DEFINITION_VERSION` fields were NULL. **Those NULLs are a failed diagnostic join, not evidence of eight missing conformed records.** The query used `r.SOURCE_RECORD_ID = o.SOURCE_RECORD_ID`, while the historical release builder's `_source_record_id()` uses `row.source_record_id or row.record_id`. It therefore excludes a legacy row whose `SOURCE_RECORD_ID` is NULL and whose `RECORD_ID` was carried into the release observation. The previous all-row reconciliation remains separate evidence; this example export does not prove the record identity needed for #193.

The corrected bounded SELECT below uses that exact builder fallback and leaves source/dataset/resource equality visible for independent inspection. It is for **representative #193 execution**, not metadata-table discovery. It returns at most one physical observation per selected measure and emitted OBSERVED/ZERO state, with no payload. `OH_LYME_PROD_READ` was denied on `SEMANTIC_OBSERVATIONS`; a later expressly authorized `OH_LYME_PROD_OWNER` attempt was denied on `GOVERNED_SOURCE_RECORDS`. It must be executed only through an existing authorized read route; do not change grants, roles, or PROD data merely for acceptance:

```sql
WITH selected AS (
  SELECT o.*
  FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_OBSERVATIONS AS o
  JOIN ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.CURRENT_RELEASE_V AS cr
    ON cr.RELEASE_ID = o.RELEASE_ID
   AND cr.BUNDLE_SHA256 = '038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026'
  WHERE o.RELEASE_ID = 'governed-2026-09-18-unknown-coverage'
    AND o.MEASURE_ID IN ('rucc_2023', 'population_2022',
      'svi_percentile_2022', 'uninsured_percentile_2022',
      'uninsured_percent_2022')
    AND o.VALUE_STATE IN ('OBSERVED', 'ZERO')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY o.MEASURE_ID, o.VALUE_STATE
    ORDER BY o.FIPS, o.OBSERVATION_ID
  ) = 1
)
SELECT o.RELEASE_ID, o.OBSERVATION_ID, o.MEASURE_ID, o.FIPS,
       o.VALUE_STATE, o.VALUE, o.TEMPORAL_WINDOW,
       o.TRANSFORMATION_VERSION, o.QUALITY_STATE, o.LIMITATIONS,
       o.RETRIEVED_AT, o.SOURCE_KEY, o.SOURCE_VERSION_ID,
       o.INGESTION_RUN_ID, o.ARTIFACT_ID, o.SOURCE_RECORD_ID,
       o.SOURCE_ROW_HASH, d.SOURCE_ID, d.DATASET_ID,
       d.RESOURCE_KEY, d.VINTAGE, d.LABEL AS SOURCE_LABEL,
       r.RECORD_ID AS CONFORMED_RECORD_ID,
       r.SOURCE_RECORD_ID AS CONFORMED_SOURCE_RECORD_ID,
       r.SOURCE_ROW_HASH AS CONFORMED_ROW_HASH,
       r.SOURCE_ID AS CONFORMED_SOURCE_ID,
       r.DATASET_ID AS CONFORMED_DATASET_ID,
       r.RESOURCE_KEY AS CONFORMED_RESOURCE_KEY,
       r.SOURCE_DEFINITION_VERSION,
       r.RETRIEVED_AT AS RECORD_RETRIEVED_AT
FROM selected AS o
LEFT JOIN ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_DATA_SOURCES AS d
  ON d.RELEASE_ID = o.RELEASE_ID
 AND d.SOURCE_KEY = o.SOURCE_KEY
 AND d.SOURCE_VERSION_ID = o.SOURCE_VERSION_ID
 AND d.INGESTION_RUN_ID = o.INGESTION_RUN_ID
 AND d.ARTIFACT_ID = o.ARTIFACT_ID
LEFT JOIN ONE_HEALTH_LYME_GAP_ATLAS_PROD.CONFORMED.GOVERNED_SOURCE_RECORDS AS r
  ON r.INGESTION_RUN_ID = o.INGESTION_RUN_ID
 AND COALESCE(NULLIF(r.SOURCE_RECORD_ID, ''), r.RECORD_ID) = o.SOURCE_RECORD_ID
 AND r.SOURCE_ROW_HASH = o.SOURCE_ROW_HASH
ORDER BY o.MEASURE_ID, o.VALUE_STATE, o.FIPS;
```

Until representative conformed authority rows are available, `validate_lineages()` cannot be run on actual #191/#193 envelopes. Do not substitute synthetic examples, the aggregate CSVs, a generated summary, or guessed record revision values. DATA #199/#200 remain open. No PROD mutation, release or source replay is implied.

## 2026-10-04 first owner-directed acceptance attempt (historical)

The access and review disposition in this section was superseded by the later,
explicit product-owner authorization and reviewed packet recorded below. Its
`ATLAS_PROD_READ` error remains an immutable audit receipt.

The Atlas product owner directed a conservative review and authorized a bounded
SELECT-only attempt using the existing `ATLAS_PROD_READ` connection. The CLI
identity SELECT, with `--warehouse COMPUTE_WH`, returned user `MATTHEWCARAWAY`,
role `OH_LYME_PROD_READ`, database `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, and warehouse
`COMPUTE_WH`. The exact corrected SELECT above was then submitted unchanged. It
failed at compilation, before returning any representative rows:

> `002003 (42S02): 01c7824f-040b-e23e-0064-2d070111f16e: SQL compilation error: Object 'ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_OBSERVATIONS' does not exist or not authorized. Your primary role OH_LYME_PROD_READ must have at least one privilege granted on TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_OBSERVATIONS.`

This is a SELECT-only access failure, not evidence of a missing table or source
record. No role switch, grant, secondary-role expansion, owner credential, or
PROD write was attempted. The repository's
[`connection-inventory.md`](../../operations/connection-inventory.md) documents
`ATLAS_PROD_RUNTIME_AUDIT` for read-only PROD runtime checks and
`ATLAS_PROD_OWNER` for owner rights, but does not establish that either may read
these physical tables for this task. Prior runtime audit also recorded `002003`
for direct `SEMANTIC_DATA_SOURCES` access. An authorized data steward/audit owner
must either execute this exact bounded query in an already-permitted session and
provide its CSV, or identify an existing approved read route. No new grant is
requested solely for acceptance.

### Conservative metadata decision record

The product-owner direction accepts county contextual use, explicit missingness,
noncausal/nonindividual limits, and exact source-version binding. It does not
assert an unevidenced scientific finding. The following recommendations separate
source/contract facts (A), product-safe policy (B), and unsupported claims (C):

| Measure | A: supported meaning | B: recommended admission | C: do not assert |
| --- | --- | --- | --- |
| `population_2022` | CDC/ATSDR `E_TOTPOP` is a county population estimate in the 2022 SVI product / 2018–2022 ACS period. | People; no numeric denominator; admit OBSERVED, genuine ZERO, and sentinel/null MISSING; retain estimate and context limitations. | Exact publication/availability date or individual risk. |
| `svi_percentile_2022` | `RPL_THEMES` is the overall SVI county percentile, 0–1, with a national county reference. | Keep percentile distinct from percent and people; admit OBSERVED, genuine ZERO, and MISSING; forbid causal/risk claims. | A person denominator or change in vulnerability from percentile differences. |
| `uninsured_percentile_2022` | `EPL_UNINSUR` ranks the county uninsured percentage, 0–1. | Use the national county reference, not a person denominator; admit OBSERVED, genuine ZERO, and MISSING. | Treat the rank as the percentage of uninsured people. |
| `uninsured_percent_2022` | `EP_UNINSUR` is a 0–100 county percentage using the civilian noninstitutionalized population. | Keep this denominator distinct from `E_TOTPOP`; admit OBSERVED, genuine ZERO, and MISSING. | Individual insurance status or disease risk. |
| `rucc_2023` | USDA ERS `RUCC_2023` is a 1–9 county category from the 2023 codebook; the accepted release requires a valid code for every selected county. | Admit OBSERVED only for this release; preserve the 2023 codebook, categorical use, and vintage-only time limitation. | Numeric distance between codes, annual observation date, causality, or individual risk. |

The source facts and sentinel behavior are documented in
[`story-199-svi-reconciliation-2026-10-02.md`](story-199-svi-reconciliation-2026-10-02.md)
and [`story-200-rucc-context-v1.md`](story-200-rucc-context-v1.md). These are
recommendations for the five complete, exact-source-bound PENDING envelopes;
the JSON was not relabeled `REVIEWED`. The #191 contract names Atlas data
stewardship and engineering as owner and requires a dated steward review. This
owner direction did not itself identify a data steward or complete that review.
The candidate meaning signatures and revision IDs remain candidate identities.

RUCC's candidate #190 `POINT_IN_TIME` definition is still incompatible with a
vintage-only source when #193 constructs a real observation: its validator
requires an exact date. The product-safe decision is to preserve `2023` as a
vintage, not assign a fabricated day. A reviewed additive vintage-time semantic
and versioned measure identity is the smallest honest contract direction; it
must be reviewed and tested before the RUCC envelope can be finalized. The
historical conformed record has no V103 revision, so a legacy identity rule must
be anchored to its actual immutable record ID, run and row hash without
pretending a V103 capture existed. Neither rule was used to fabricate a #193
PASS while the representative authority query was denied.

### Criterion-by-criterion disposition at this attempt

| DATA #199 criterion | Status | Evidence or exact gap |
| --- | --- | --- |
| Accepted field-level matrix | PASS | Existing #199 field matrix identifies retained and deferred fields. |
| People, percentage, percentile separation | PASS | Distinct measures, units, denominators and source fields in the matrix and current release. |
| Sentinel/missingness explicit and tested | PASS | Existing `svi_context` and source-mapping tests; current PROD has no missing selected SVI values, so fixture cases remain separately labeled. |
| Exact source/version/run/artifact and #188 metadata/lineage | FAIL | Aggregate authority reconciliation passes, but reviewed #191 revisions and representative #193 validation remain absent; corrected SELECT denied `002003`. |
| New field/meaning versioned and reviewed | NOT APPLICABLE | No new field or meaning is being published in this accepted scope; the proposed #191 envelopes still require review before admission. |
| Fixture versus governed evidence separated | PASS | Existing #199 audit, PR #600 aggregate PROD receipt, and this denied representative query remain distinct. |
| Deferred fields disposition | PASS | Existing #199 matrix explicitly defers other SVI factors, vintages and separate adapters. |

| DATA #200 criterion | Status | Evidence or exact gap |
| --- | --- | --- |
| Delivered-versus-gap matrix | PASS | Existing #200 matrix covers RUCC and selected SVI context. |
| RUCC codebook/vintage explicit and tested | PASS | Nine-category 2023 codebook and source-domain tests; no annual-date interpretation is claimed. |
| Geography/missingness deterministic | PASS | Existing numeric/string, FIPS, duplicate and missing-mapping tests plus 3,144/3,144 PROD aggregate reconciliation. |
| #188 metadata/lineage directly used | FAIL | Reviewed RUCC metadata and real representative #193 execution remain absent; corrected SELECT denied `002003`. |
| Existing release preserved or versioned | PASS | Pinned release/bundle unchanged; this PR contains no PROD change. |
| Unsupported/deferred fields disposition | PASS | Existing #200 matrix defers broader demographics and annual API projection. |

Neither issue is ready to close. The exact next evidence action is an
owner-authorized read of the corrected bounded query; the dated #191 steward
decisions and versioned vintage/legacy rules must then be applied before a
real `validate_lineages()` result or PR merge-readiness claim.

## Later explicit owner authorization and final repository review

The Atlas product owner explicitly authorized `ATLAS_PROD_OWNER` for this
SELECT-only acceptance audit and approved the five conservative contextual
definitions above. ADR 0035 names Atlas product/data stewardship and
engineering as the decision owner; the #191 contract requires a dated review
but does not reserve contextual metadata approval to another named person or
external domain scientist. This owner decision is therefore recorded as the
steward review for these bounded product definitions. It does not approve a
causal, individual-risk, or novel scientific assertion. The review date is
2026-10-04; the reviewer authority is the Atlas product owner, Matthew
Caraway, acting under ADR 0035. The JSON contract has no reviewer-name field,
so the authority statement is in this durable record rather than an
unsupported JSON extension.

| Reviewed measure | Semantic version | Meaning signature | Metadata revision ID |
| --- | --- | --- | --- |
| `population_2022` | `1.0.0` | `71a919c8ef66d528205c88ffb3d863456567bf1c835b733aff1f4a3767aca9d9` | `metadata-revision:v1:b848914c705a99dcfe37ce9d638a6f6a939118fbc5662a6bc56a21e9226c669c` |
| `svi_percentile_2022` | `1.0.0` | `661c02aa84f82c34a2770a8ff60b7734c880dd87d695cc7c1f0f72ff1a217f8b` | `metadata-revision:v1:144b7fecaa83ed51d17ff78b9794607252837a4a90ec1d9cfae2ca6b25ab5ccf` |
| `uninsured_percentile_2022` | `1.0.0` | `9d3bc797a25f42148b62f95aac519ff80df789149bcabca8ab60106313c5822c` | `metadata-revision:v1:93ec76b97a9d485f6117487f3454bb81dff23f2df2f7d656cb3fe1892b571e53` |
| `uninsured_percent_2022` | `1.0.0` | `c7ae99b36fb08920f8260c81ff10948d1960b4615a9aa91d2ffefbe6c4aa0ef1` | `metadata-revision:v1:9a8ee29874e817ac83aade33b313bcd33f54eeaf3daf9962ae37e31980fbb14b` |
| `rucc_2023` | `2.0.0` | `20a560603de7c667ed2b1806dc9ddd230abf28df1f6480dae1eef3ff0fd809a9` | `metadata-revision:v1:cc303005813febd67830aea1e4d1cec3042e4cab442234dec36da283f98f010b` |

`validate_metadata_revisions()` passes for the five reviewed envelopes against
the two exact approved source-version tuples above. The review updates the
meaning/revision digests but does not create a PROD metadata table, alter an
existing physical observation, or claim consumer/public admission.

RUCC's source-faithful temporal correction adds `VINTAGE_YEAR`, which accepts
exactly `YYYY` and rejects an exact day. Because time meaning is part of the
#190 signature, reviewed `rucc_2023` uses semantic version `2.0.0` and new
#192 mapping identity `rucc_vintage_2023`. The historical `rucc` point-date
mapping and fixed release remain untouched; they are not evidence of a
publisher observation day. Existing #190/#191/#192 governance tests prove
that the new definition is distinct and that no old mapping was silently
rewritten. A future #193 authority snapshot may derive a legacy record
revision from the immutable historical `(ingestion_run_id, record_id,
source_row_hash)` tuple, clearly labeled as a legacy adapter identity rather
than a nonexistent V103 capture; that rule must be applied to actual rows and
checked against record uniqueness before a live PASS can be claimed.

### Owner-role read-only query receipt

The `snow sql -c ATLAS_PROD_OWNER --warehouse
OH_LYME_PROD_INGEST_XS_WH` identity SELECT returned `MATTHEWCARAWAY`,
`OH_LYME_PROD_OWNER`, database `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, null current
schema, and `OH_LYME_PROD_INGEST_XS_WH`. The exact corrected SELECT above was
then submitted under the same connection and warehouse. It failed at SQL
compilation before any row could be returned:

> `002003 (42S02): 01c7833c-040b-e306-0064-2d0701120826: SQL compilation error: Object 'ONE_HEALTH_LYME_GAP_ATLAS_PROD.CONFORMED.GOVERNED_SOURCE_RECORDS' does not exist or not authorized. Your primary role OH_LYME_PROD_OWNER must have at least one privilege granted on TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.CONFORMED.GOVERNED_SOURCE_RECORDS.`

This proves the role can compile past `PRESENTATION.SEMANTIC_OBSERVATIONS`,
but not that the representative record joins pass. No alternate identity,
secondary role, privilege change, or PROD mutation was attempted. The earlier
15,720-link aggregate reconciliation remains valid independent evidence,
but the corrected representative query has **no result**. The explicit #193
result is **FAIL / NOT EXECUTABLE against actual authority rows**: the existing
`validate_lineages()` cannot be run on a complete live snapshot while this
conformed-record read is denied. Neither issue is complete solely from
reviewed metadata and the aggregate.

### Current acceptance decision by issue

| DATA #199 criterion | Decision | Evidence |
| --- | --- | --- |
| Field-level source-to-semantic matrix | PASS | Existing #199 selected-field matrix and explicit deferred scope. |
| Population, percentage, percentile separation | PASS | Four distinct reviewed definitions, source fields, units, and denominator/reference policies. |
| Sentinel and missing handling | PASS | Source-domain tests retain `MISSING`, genuine `ZERO`, and observed values distinctly; reviewed envelopes admit exactly those states. |
| Source/version/run/artifact lineage and #188 metadata | FAIL | Exact aggregate source lineage and five reviewed metadata revisions pass, but the representative historical record join and `validate_lineages()` are unavailable under the authorized owner role. |
| New field or meaning versioned and reviewed | NOT APPLICABLE | No new SVI field or scientific meaning is published; initial metadata revisions are owner-reviewed. |
| Fixture versus governed evidence distinguished | PASS | Tests, current release aggregates, and denied live query are labeled separately. |
| Unsupported/deferred fields disposition | PASS | Existing #199 matrix explicitly defers other source fields/vintages and separate adapters. |

| DATA #200 criterion | Decision | Evidence |
| --- | --- | --- |
| Delivered-versus-gap matrix | PASS | Existing #200 accepted-scope matrix. |
| RUCC codebook/vintage explicit and tested | PASS | Frozen 2023 codebook; reviewed `VINTAGE_YEAR` semantic v2 and source-mapping tests reject invented day. |
| Geography and missingness deterministic | PASS | Existing FIPS, duplicate, code-domain, and missing-mapping tests; 3,144/3,144 all-row PROD reconciliation. |
| #188 metadata/lineage used directly | FAIL | Reviewed RUCC metadata exists, but actual representative #193 historical-record validation cannot run after `002003` owner-role denial. |
| Release preserved or versioned | PASS | Versioned semantic identity is additive; physical release and pointer were not changed. |
| Unsupported/deferred fields disposition | PASS | Existing #200 matrix excludes broader demographics, other RUCC attributes, and annual API projection. |

No issue closure, PR merge, or live #193 PASS is warranted while the required
historical conformed-record authority cannot be read. A limitation can express
uncertain scientific time or interpretation; it cannot substitute for a
required source-record identity in #193.
