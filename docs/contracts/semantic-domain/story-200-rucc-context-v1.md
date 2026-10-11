# DATA200: accepted RUCC and demographic context contract v1

Owner: Atlas Data. Scope: residual reconciliation of the selected baseline,
not new sources or measures. Reviewed against main `4b2fb225` on 2026-10-02.
DATA199 owns SVI details and the eventual combined DATA202 compatibility PR.

## Delivered versus gap matrix

| Accepted scope | Delivered evidence | Residual disposition |
| --- | --- | --- |
| County rurality category | `usda_ers_rucc_2023` definition v1; `Attribute=RUCC_2023`, `Value` to `rucc_2023`; #192 mapping | Freeze codebook below; enforce code domain and exact vintage; source-specific negative tests |
| Population context | SVI `E_TOTPOP` to `population_2022` | Existing selected ACS estimate, not RUCC category or RUCC census population; DATA199 validates period/missingness |
| Socioeconomic vulnerability | SVI `RPL_THEMES` to `svi_percentile_2022` | Existing percentile, not a percentage; DATA199 owns validation |
| Insurance context | SVI `EPL_UNINSUR` to `uninsured_percentile_2022`; `EP_UNINSUR` to `uninsured_percent_2022` | Distinct percentile and percentage; DATA199 owns validation |
| Other RUCC attributes | Source-faithful retained CSV and generic lineage | Audit only; no new semantic population/demographic projection |
| Additional age, sex, race/ethnicity, income, education, poverty, or demographic strata | No additional measure selected under this residual scope | Deferred to explicit future product/source decision; no implied missing implementation |
| Annual contextual observation API | Existing county atlas and semantic observations; V127 annual view excludes RUCC/ACS | Remains excluded: a codebook vintage is not an annual observed interval; ACS needs its own period contract |

## Frozen 2023 interpretation

The following concise labels describe the selected codebook. Authoritative
definitions and geographic qualifications are in the [USDA ERS documentation](https://www.ers.usda.gov/data-products/rural-urban-continuum-codes/documentation)
(checked 2026-10-02; publisher page updated 2025-01-07).

| Code | Label |
| --- | --- |
| 1 | Metro: area population at least 1 million |
| 2 | Metro: area population 250,000 to 1 million |
| 3 | Metro: area population below 250,000 |
| 4 | Nonmetro: urban population at least 20,000; adjacent |
| 5 | Nonmetro: urban population at least 20,000; nonadjacent |
| 6 | Nonmetro: urban population 5,000 to 20,000; adjacent |
| 7 | Nonmetro: urban population 5,000 to 20,000; nonadjacent |
| 8 | Nonmetro: urban population below 5,000; adjacent |
| 9 | Nonmetro: urban population below 5,000; nonadjacent |

Adjacency refers to metro areas under the publisher's geographic/commuting
criteria. Metro categories use metro-area population, not county population.
The 2023 urban threshold changed from 2,500 to 5,000; older codebooks cannot be
substituted or interpreted as a comparable time series without review. RUCC
is county context, not an individual-risk, causal, or predictive measure.
Do not average categories or interpret category increments as measured distances.

The 2026-10-04 owner-reviewed #190/#191 semantic definition is
`rucc_2023` version `2.0.0` with `VINTAGE_YEAR: 2023`, bound to the same
approved source version. It does not assign a publisher observation day. The
additive `rucc_vintage_2023` #192 mapping preserves the historical `rucc`
point-date mapping as a separate old identity. No physical historical row,
published release pointer, or source artifact is rewritten by this semantic
correction. Full #193 historical-record validation remains a separate gate.

## Geography, missingness and provenance

The existing assembler accepts numeric/string representations of integral
codes 1–9, preserving five-digit source FIPS strings including leading zeros.
It does not guess stripped leading zeros or fabricate a county crosswalk.
Duplicate selected attributes block, including identical duplicates. Every
canonical SVI county must have a valid selected RUCC code; a missing mapping,
suppressed sentinel, null, nonfinite, fractional, boolean or out-of-domain code
blocks candidate assembly. Unknown never becomes zero or a default category.
Other attributes cannot fill RUCC gaps. Extra source counties remain retained
in RAW lineage but do not extend canonical release coverage. Boundary changes
(including Connecticut county equivalents) need exact accepted identities;
no historical county coercion is introduced.

Reuse #188/#190–#195 directly: existing measure/indicator identity, metadata,
source mapping, source gate, observation source-row/hash, source-version/run/
artifact/retrieval anchors and immutable release lineage. A 2023 codebook label
does not establish publisher availability time; use retained capture lineage.
The periodic source cadence does not imply an annual replacement vintage.

## Version and regression boundary

This contract v1 adds fail-closed code-domain and vintage validation. Source
definition v1, accepted values, transformation, 14 observation slots, measure
metadata and release schema remain unchanged. No scientific definition or
published value changes; no ingestion, migration, grants or deployment.
Candidate validation completes before persisted release insertion; failures
cannot replace the current pointer. A future definition/output change must be
explicitly versioned and pass #195 release regression checks.

Focused evidence: `tests/test_rucc_context_contract.py`, existing
`tests/test_semantic_release.py`, and #195 governance fixtures. The existing
approved source tuple is retained in
[`governed-2026-09-15-manifest.json`](../semantic-release/governed-2026-09-15-manifest.json):
version `87872b36-93ab-4a34-b70e-29569192cb48`, run
`f65bd68a-27de-4ad4-81a5-424ee24af3b6`, artifact
`usda_ers_rucc_2023:ec455ee2a8bc5fc8e070575ea5bee7dc`, SHA-256
`ec455ee2a8bc5fc8e070575ea5bee7dce46fc6037f8c3449cbf56e8b45331fa7`.
These are retained historical evidence, not a new execution claim.

Read-only DEV acceptance on 2026-10-02 used `ATLAS_DEV_READ`, verified as
`OH_LYME_DEV_READ` / `ONE_HEALTH_LYME_GAP_ATLAS_DEV` /
`OH_LYME_DEV_INGEST_XS_WH`: `CURRENT_COUNTY_ATLAS_V` contained 3,144 counties,
zero null/fractional/out-of-domain RUCC codes. The current release was
`governed-2026-09-17-unknown-coverage`, with 3,144 distinct five-digit FIPS.
Counts for codes 1–9 were respectively 443, 385, 358, 201, 76, 379, 247, 466,
589, matching the retained alpha baseline. Current metadata reported RUCC
`2023` and SVI `2022 (2018-2022 ACS)`. This confirms the current value
domain, not new-code deployment, PROD acceptance or live API behavior.

## DATA202 handoff

Combine only after DATA199 and DATA200 stabilize. Check exact county identity,
SVI 2018–2022 survey period versus RUCC 2023 classification, observation versus
availability time, category versus population/percentile/percentage, stale
valid vintage versus broken refresh, suppressed/unknown context, run/artifact
revision lineage and preservation of the last approved release. DATA199 owns
the shared compatibility matrix/tests; this PR introduces no duplicate shared
DATA202 changes. Climate/release owners retain their work and reserved V136.
