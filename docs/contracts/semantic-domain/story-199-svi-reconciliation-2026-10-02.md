# DATA199 SVI residual reconciliation

Review candidate, 2026-10-02. Scope: existing `cdc_atsdr_svi_2022_county`,
`cdc_atsdr_svi` / `atsdr-svi-2022-county-layer`, definition 1. No new source,
field, acquisition, source activation, score, migration or release is proposed.

## Delivered field matrix

All numeric fields are publisher-reported county context for the **2018–2022
ACS five-year period**, SVI product vintage 2022. Vintage is not publication,
availability or retrieval time. The source definition's annual cadence does not
authorize replacing this fixed vintage with a newer product. An old, correctly
pinned vintage is not by itself evidence of a failed refresh.

| Source field | Existing release measure/output | Unit/domain | Denominator/reference | Delivery/disposition |
| --- | --- | --- | --- | --- |
| `E_TOTPOP` | `population_2022` / `population` | people, nonnegative estimate | County total population, ACS 2018–2022 | Delivered in 14-slot county release; not a separately registered #192 adapter |
| `RPL_THEMES` | `svi_percentile_2022` / `svi_percentile` | percentile, 0–1 | National county ranking population for this product/vintage, not a person denominator | Delivered; existing #192 `svi` rule reused |
| `EP_UNINSUR` | `uninsured_percent_2022` / `uninsured_percent` | percent, 0–100 | Total civilian noninstitutionalized population; not `E_TOTPOP` and not an uninsured count | Delivered in county release; separate #192 adapter deferred |
| `EPL_UNINSUR` | `uninsured_percentile_2022` / `uninsured_percentile` | percentile, 0–1 | National county ranking of `EP_UNINSUR` | Delivered in county release; separate #192 adapter deferred |
| `STCNTY` | `county_fips` / `fips` | Exact five-character county FIPS | County/native publisher identity | Delivered; leading zero retained, no numeric padding or county-name join |
| `STATE`, `ST_ABBR`, `COUNTY`, `LOCATION` | County/state identity and retained source record | Text | Publisher labels | Retained; `LOCATION` is not a new measure |
| `geometry` | County display `geometry_json` | GeoJSON Polygon/MultiPolygon, EPSG:4326 | Publisher 2022 county boundary, `maxAllowableOffset=0.01` | Display only; never substitute for frozen TIGER 2025 analytical area weights |
| Themes, other social factors, MOEs, flags, tract/state rankings, other vintages | None | Not selected | Not established in this bounded contract | Deferred; no broad field expansion, precision/uncertainty inference, or new semantic mappings |

Authoritative field/sentinel descriptions: [CDC/ATSDR SVI 2022 documentation](https://www.atsdr.cdc.gov/place-health/media/pdfs/2024/10/SVI2022Documentation.pdf),
especially the missing-data notes and `EP_UNINSUR` / `EPL_UNINSUR` dictionary.
Population is an estimate; percentile differences are not percentage-point
changes in population characteristics. No averaging/re-ranking percentiles,
causal inference, diagnosis, individual risk, or automatic ML/score admission.
Mixed-vintage descriptive context must retain each period explicitly; it is not
a contemporaneous join. Cross-vintage equivalence requires #195 review.

## Minimal correction and version boundary

`svi_context.numeric_value` now handles the four retained fields at the semantic
projection boundary. Publisher `-999` (numeric or string), null and empty input
produce null with the existing `MISSING` observation state. Zero remains `ZERO`.
The publisher sentinel is distinguishable from null in the immutable source
record and lineage; `MISSING` does not assert suppression, not-reported or zero.
Other negative values, nonnumeric/boolean values, NaN/infinity and invalid
percentage/percentile ranges fail closed. Generic ingestion normalization and
RAW bytes are unchanged. The existing #192 SVI mapper uses the same boundary;
explicit null source states continue through the existing state handling.
The SVI mapper also requires the exact ACS 2018–2022 observation period;
a correct 2022 source-vintage label cannot authorize a 2023 observation period.

New candidate SVI observations record `svi_numeric_projection_v2`; other county
observations retain `semantic_county_assembly_v1`. No meaning, unit, denominator,
measure identity, source-definition version, historical observation or published
release is rewritten. Review this candidate before any protected publication.
Existing valid numeric values and geometry remain unchanged; legacy sentinel
observations, if found outside the inspected DEV release, require explicit
new-release reconciliation rather than historical updates.

## Acceptance-to-evidence matrix

| #199 criterion | Concrete implementation / validation | Runtime boundary |
| --- | --- | --- |
| Field matrix complete | Matrix above; source YAML; `_insert_hierarchy`, `_county_observations` | Four distinct measures observed in DEV metadata view |
| Estimates/percentages/percentiles distinct | Existing measure IDs retained; `svi_context` separate domains; `test_percentage_and_percentile_domains_remain_distinct` | DEV has people, percent and percentile units with ACS period |
| Missing/sentinel explicit and tested | `test_missing_and_sentinel_never_become_observed_numbers`, `test_release_sentinel_preserves_raw_and_exact_lineage`, mapper boundary test | Current DEV has no missing/invalid overall SVI; synthetic sentinel cases are not live replay |
| #188 metadata and full lineage intact | Existing #190–#195 validators; `test_release_sentinel_preserves_raw_and_exact_lineage`; affected semantic regression suites | Full source/version/run/artifact table inspection denied to `OH_LYME_DEV_READ`; not claimed verified |
| New meaning/field versioned and reviewed | No new meaning/field; numeric projection v2 explicitly recorded; draft PR review required | No release published |
| Fixture/integration evidence separated | Fixture tests below; bounded view reads below | No reingestion, PROD mutation or live API acceptance claim |
| Deferred fields explicit | Matrix dispositions above | No inference of complete #191/#192 adapters for unregistered fields |

`tests/test_svi_context.py` additionally rejects duplicate county identities,
malformed FIPS and incompatible authority vintage while preserving generic
normalization. #188 mapping/lineage/metadata/governance/consumer tests remain the
shared authority. The consumer SQL observation view admits human measures only;
SVI remains available through the county atlas and measure metadata views.
This story does not expand that approved API observation allowlist.

### Full-path metadata state boundary

The checked-in #191 generic synthetic SVI example admits only `OBSERVED`,
`UNKNOWN` and `UNAVAILABLE`. Its lack of `ZERO`/`MISSING` is a fixture coverage
gap; it is not evidence about unread reviewed metadata. #190 defines both states,
and the existing county release already emits them. Full `map_record` tests now
exercise sentinel, null, empty, zero, observed and explicit unknown/unavailable
values with a **new synthetic candidate metadata/measure version 1.1.0**, updating
its meaning signature and revision identity. This is test-only, remains `PENDING`,
and cannot authorize live mapping. No registry or live definition is versioned by
this fixture. The original example remains unchanged. Additional negative tests
prove that mapping still rejects `MISSING`/`ZERO` under metadata that excludes
them and that pending candidate metadata fails outside fixture mode. Actual
reviewed SVI metadata state compatibility must be audited before full governed
#192 sentinel/zero runtime acceptance can be claimed; no automatic widening or
unversioned meaning change is introduced.

## Authorized DEV evidence (2026-10-02)

Read-only `snow sql -c ATLAS_DEV_READ`: effective role `OH_LYME_DEV_READ`,
database `ONE_HEALTH_LYME_GAP_ATLAS_DEV`, warehouse
`OH_LYME_DEV_INGEST_XS_WH`; no alternate login or grants used.

`PRESENTATION.CURRENT_COUNTY_ATLAS_V` for
`governed-2026-09-17-unknown-coverage`: 3,144 rows / 3,144 unique FIPS;
0 malformed FIPS, out-of-range SVI/uninsured percentiles, out-of-range uninsured
percentages, negative populations, missing SVI, or non-polygon geometry types.
This type check is not proof of topology/analytical geometry validity.
`CURRENT_SOURCE_METADATA_V` retains the exact CDC source/dataset, vintage
`2022 (2018-2022 ACS)` and noncausal/nonindividual interpretation note.
`CURRENT_MEASURE_METADATA_V` returns all four distinct measures with the
`2018-2022 ACS` period and existing limitations.

Direct `PRESENTATION.SEMANTIC_DATA_SOURCES` SELECT failed with Snowflake
`002003` (does not exist or not authorized). Therefore exact run/artifact/checksum,
reviewed #191 metadata revisions and source-backed projection replay remain
unverified in this session. Parent can supply authorized audit evidence; no
access expansion or source run is justified merely to remove this limitation.
DEV views are actual governed consumer-SQL evidence, not deployed changed-code
acceptance or a live REST/UI check. PROD and publication evidence remain separate.

## DATA202 handoff

SVI tests above contribute source-domain, missingness, FIPS/duplicate and
cross-vintage and observation-period coverage. Parent coordinated the shared
#192 SVI fixture correction to a valid percentile of 0.5 and ACS 2018–2022;
the negative tests retain invalid-range and incompatible-period assertions.
Parent assigned this lane the eventual coherent #202 PR
after SVI/RUCC contract review. Collect RUCC findings through parent before
editing shared tests; do not create a competing validation owner. Remaining
cross-source freshness, availability-time and blocking-release cases should
reuse #191/#195 and #250/#278 controls. V136 belongs to climate draft #552;
no migration number or deployment is consumed here.
