# DATA #199/#200 metadata and legacy-lineage review handoff

Status: **five source-bound #191 candidates prepared; steward review and #193 live validation pending**. This supplements the [PROD source/record reconciliation](data-199-200-prod-authority-reconciliation-2026-10-03.md). It does not revise the published release, approve metadata, or assert a live #193 result.

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

## Five review candidates

[Candidate JSON](data-199-200-metadata-review-candidates-2026-10-04.json) contains complete, validator-accepted #191 envelopes bound to the exact PROD SVI (`b8b6bf61-c6a3-4538-b0df-1b88c61720b1`) and RUCC (`87872b36-93ab-4a34-b70e-29569192cb48`) source versions. Each has an exact candidate `metadata_id`, semantic version, metadata revision, meaning signature, content-derived revision ID, explicit provenance/applicability/freshness/quality states, limitations, and `INTERNAL` visibility. **Every candidate remains `PENDING`; no reviewed date or authority has been fabricated.** Candidate revision IDs will change if the steward amends fields or records review. The candidate semantic version `1.0.0` is proposed #190 identity, not inferred solely from the physical release's schema version.

| Measure | Source field | Proposed meaning and review focus | Actual PROD states in PR #600 |
| --- | --- | --- | --- |
| `population_2022` | SVI `E_TOTPOP` | ACS 2018–2022 county total population estimate; `NONE` ratio denominator | 3,144 OBSERVED |
| `svi_percentile_2022` | SVI `RPL_THEMES` | National county percentile reference, not a person denominator | 3,143 OBSERVED; 1 ZERO |
| `uninsured_percentile_2022` | SVI `EPL_UNINSUR` | National county percentile ranking of `EP_UNINSUR` | 3,143 OBSERVED; 1 ZERO |
| `uninsured_percent_2022` | SVI `EP_UNINSUR` | Percent of civilian noninstitutionalized population, distinct from `E_TOTPOP` | 3,143 OBSERVED; 1 ZERO |
| `rucc_2023` | RUCC `RUCC_2023` | 2023 codes 1–9; category/vintage rather than continuous distance or annual value | 3,144 OBSERVED |

For the four SVI candidates, `OBSERVED`, `ZERO`, and `MISSING` are proposed permitted states: the first two are emitted in PROD as above; `MISSING` is the explicit sentinel/null handling in the #199 residual contract, not a current PROD count. RUCC proposes `OBSERVED` only because the existing assembler blocks missing, zero and out-of-domain codes. The steward must approve these full state policies, definitions, reference-population wording, interpretation/use limits, and source-bound provenance. The candidate's `GOVERNED_GENERATED` authority classification means the wording was assembled from existing governed documents, not directly copied as publisher text or already reviewed by a steward. The metadata revision date records candidate authorship only. Unknown observation dates, publisher publication dates, retrieval times and uncertainty are explicitly unknown rather than inferred from a vintage or release approval. Before `REVIEWED`, the steward must decide whether the proposed #190 temporal and methodology identities faithfully describe the historical release.

## Exact #193 legacy boundary

PR #600 proves all 15,720 selected observation links have one historical `CONFORMED.GOVERNED_SOURCE_RECORDS` match by run, source record ID and row hash; V103 capture absence is expected for these runs. That aggregate does not supply the actual five-to-eight example row envelopes required for `validate_lineages()`. The legacy conformed table also has no `record_revision`, `artifact_id`, or `source_version_id` columns. The separately verified release source tuple and artifact ledger bind the latter two. A legacy record revision must be explicitly defined from retained immutable content and reviewed, rather than copied from a nonexistent V103 capture. #190's `POINT_IN_TIME` RUCC candidate likewise requires an exact date while the physical release records only vintage `2023`; assigning January 1 or December 31 would invent time semantics. The steward/release owner must resolve that mapping or approve a versioned contract correction before claiming RUCC #193 PASS. For SVI, any conversion from the ACS 2018–2022 label to exact ISO start/end dates also needs an explicit reviewed mapping. Computed #190 semantic revision membership must be tied one-to-one to the physical release observation IDs; the bundle hash alone does not provide it.

One additional bounded SELECT is useful for **representative #193 execution**, not metadata-table discovery. It returns at most one physical observation per selected measure and emitted OBSERVED/ZERO state, with exact legacy conformed record identity and no payload. Run it in Snowsight under the existing `OH_LYME_PROD_READ` role, `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, and `COMPUTE_WH`; do not change grants, roles, or PROD data:

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
       r.SOURCE_DEFINITION_VERSION, r.RETRIEVED_AT AS RECORD_RETRIEVED_AT
FROM selected AS o
LEFT JOIN ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_DATA_SOURCES AS d
  ON d.RELEASE_ID = o.RELEASE_ID
 AND d.SOURCE_KEY = o.SOURCE_KEY
 AND d.SOURCE_VERSION_ID = o.SOURCE_VERSION_ID
 AND d.INGESTION_RUN_ID = o.INGESTION_RUN_ID
 AND d.ARTIFACT_ID = o.ARTIFACT_ID
LEFT JOIN ONE_HEALTH_LYME_GAP_ATLAS_PROD.CONFORMED.GOVERNED_SOURCE_RECORDS AS r
  ON r.INGESTION_RUN_ID = o.INGESTION_RUN_ID
 AND r.SOURCE_RECORD_ID = o.SOURCE_RECORD_ID
 AND r.SOURCE_ROW_HASH = o.SOURCE_ROW_HASH
 AND r.SOURCE_ID = d.SOURCE_ID
 AND r.DATASET_ID = d.DATASET_ID
 AND r.RESOURCE_KEY = d.RESOURCE_KEY
ORDER BY o.MEASURE_ID, o.VALUE_STATE, o.FIPS;
```

Until review decisions and the representative authority rows are available, `validate_lineages()` cannot be run on actual #191/#193 envelopes. Do not substitute PENDING examples, the aggregate CSVs, a generated summary, or guessed temporal/record revision values. DATA #199/#200 remain open. No PROD mutation, release or source replay is implied.
