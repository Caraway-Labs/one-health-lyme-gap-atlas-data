# DATA #199/#200: bounded PROD SVI/RUCC authority reconciliation

2026-10-04 follow-up: the [#191 metadata and #193 legacy-lineage review handoff](data-199-200-metadata-review-handoff-2026-10-04.md) inventories the human-run exports, initial PENDING candidates, later five owner-REVIEWED revisions, and the authorized owner-role SELECT denial on the historical conformed-record table. This document retains its as-of bounded source/record PASS; the later handoff is the current full-acceptance status.

Status: **source, release, and historical record correspondence PASS; full acceptance DEFER**. This record supplements the [SVI residual audit](story-199-svi-residual-audit-2026-10-03.md) and [RUCC context contract](story-200-rucc-context-v1.md). It does not change either contract, approve metadata, or close either issue.

## Scope and receipt

On 2026-10-03, an authorized human operator ran SELECT-only queries in Snowflake Snowsight. The reported session used `OH_LYME_PROD_READ`, `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, and `COMPUTE_WH`. The queries pinned current release `governed-2026-09-18-unknown-coverage` and bundle SHA-256 `038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026`. Four aggregate CSV exports were supplied for independent interpretation. They contain no RAW payloads or case-level values and are not committed:

| Export suffix | Purpose | Local CSV SHA-256 |
| --- | --- | --- |
| `2259` | Five-measure observation aggregates | `68e7b1dd818ee12cad4f0440eccb2b1faf9e56c365caa36df9b4ad4bd6b3fdae` |
| `2303` | Source-version and historical storage diagnostic | `2be6a91b0eec321350feffd95a11de87eabcd3677257bba6232d83dd1dde12d6` |
| `2305` | Observation-to-conformed-record and geography correspondence | `6ac0396ee86ddef7172011f20b3e8447fac8d9f9aaab500a58e52fe55600d031` |
| `2306` | Manifest, approval, run, and artifact digest check | `0d47305473c66ddd4a9889641a4c86545de92fa05c591d743b48603caf63c38e` |

This is a human-run PROD read receipt, distinct from fixture tests, historical workflow receipts, a fresh source replay, or an executed #193 validator. The result is limited to the pinned release and the selected five measures.

## Observations and value states

Each measure has 3,144 observations, 3,144 distinct five-digit FIPS, zero invalid FIPS, one period and one transformation version. Every row has a source record ID and a syntactically valid SHA-256 row hash. The observation source/version/run/artifact tuple matches the release source row. The periods are `2022 (2018-2022 ACS)` for SVI and `2023` for RUCC; all report `semantic_county_assembly_v1`.

| Measure | OBSERVED | ZERO | MISSING | Other actual state |
| --- | ---: | ---: | ---: | ---: |
| `population_2022` | 3,144 | 0 | 0 | 0 |
| `svi_percentile_2022` | 3,143 | 1 | 0 | 0 |
| `uninsured_percentile_2022` | 3,143 | 1 | 0 | 0 |
| `uninsured_percent_2022` | 3,143 | 1 | 0 | 0 |
| `rucc_2023` | 3,144 | 0 | 0 | 0 |

The first aggregate query mistakenly counted `REPORTED` rather than the release's `OBSERVED` state, so its `OTHER_STATE_COUNT` column is **not an invalid-state count**. Reclassifying it with the release's actual `OBSERVED`/`ZERO`/`MISSING` vocabulary gives the table above. This does not establish that a steward-reviewed metadata revision admits `ZERO` or `MISSING`.

## Authority reconciliation

Both `context_svi` and `context_rucc` source-version rows exist with `APPROVED` status, an approval decision, and matching resource key. Their source-version rows do not carry run or artifact IDs. The first query's 3,144-per-measure `VERSION_MISMATCH_COUNT` therefore came from an invalid null comparison, not an observed conflict. The corresponding release source row matches the pinned manifest's version, run and artifact IDs. Both ingestion runs are `COMPLETED`; both retained artifact rows belong to those runs, have valid SHA-256 shape, and match the manifest's SHA-256 exactly.

The pinned runs have no V103 `GOVERNED_SOURCE_RECORD_REVISIONS` captures. The historical `CONFORMED.GOVERNED_SOURCE_RECORDS` relation has 3,144 SVI rows and 9,703 RUCC rows for the respective runs. The first query's `NO_MATCHING_CAPTURE_COUNT` joined V103 alone and is therefore not evidence of missing historical records. A bounded join against the historical relation found exactly one matching run, source record ID, and row hash for every one of the 15,720 selected semantic observations. There were zero absent or ambiguous record matches, zero FIPS mismatches or unreadable FIPS, and zero RUCC `RUCC_2023` attribute mismatches. The four SVI measures reuse the same 3,144 source records; 15,720 is the number of semantic observation links, not unique source records.

The earlier [build receipt](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/35328355391) and [publication receipt](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/35362701191) bind this historical manifest to the served bundle. The new operator aggregates strengthen that evidence with current PROD source, artifact and per-observation correspondence. They do not supply a current record-revision authority snapshot or execute `validate_lineages()`.

## Decision and next gate

**DATA #199 and #200 remain open.** The bounded source/record reconciliation is PASS for the pinned current PROD release. Full #191 metadata admission and #193 live authority validation are DEFER: no actual steward-`REVIEWED` metadata envelopes were supplied for the five measures. The `PENDING` synthetic examples cannot stand in for them. #191 is storage-neutral; this audit does not presume a metadata table or manufacture revisions.

The steward/release owner should provide the five authoritative reviewed envelopes bound to the selected measure and exact source version, including semantic version, metadata revision and revision ID, meaning signature, review date, allowed value states, applicability, denominator/reference and provenance. Validate emitted `OBSERVED` and `ZERO` states and the intended `MISSING` policy. Then assemble an actual historical authority snapshot under existing access and run the #193 validators, explicitly handling the legacy conformed records rather than treating absent V103 captures as missing data. Do not infer a run/artifact link from null fields in the source-version row; use the separately verified manifest, run, artifact and record receipts. Any changed scientific meaning or state policy needs a reviewed versioned decision.

No source acquisition, ingestion, PROD write, grant, credential change, release pointer move, public API change, or ML admission was performed. SVI and RUCC remain contextual county evidence, not causal, individual-risk or Lyme outcome labels.
