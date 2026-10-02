# Canonical provenance interoperability audit v1

DATA #473. Audited code: `4b2fb225d7c8ca1e005b60d93301f46ad3c410a8` (main, 2026-10-02).
This is a repository contract audit, not a Snowflake query, standards conformance
certification, or source-backed clinical integration. The accompanying
`provenance-readiness-v1.json` indexes existing machine-readable contracts and
executable evidence. It is an audit inventory, not another provenance model.

Review refresh: main `a46339b` was merged without conflicts. V128 publisher,
NULL source timestamps and method identity evidence is specifically
`migrations/V128__current_source_methodology_metadata.sql` and
`tests/test_current_source_methodology_projection.py`; the older
`test_current_semantic_metadata_views.py` covers V123/V124 instead.

## Criterion to evidence

| Required fact | Delivered contract and evidence | Remaining boundary |
| --- | --- | --- |
| Source/publisher | #191 provenance; #193 authority joins; V128 source metadata | V128 only attributes publisher for the exact approved human tuple; other publishers remain NULL until governed. |
| Dataset/version/vintage | #190 provenance anchors; #192 mapping registry; #193 exact version joins | Source-definition version, source-version identity, vintage, semantic version and release version are distinct. Mapping registry entries do not prove live approval. |
| Source field/canonical measure | #192 registry `field` and `measure_id`; `map_record()` | Incidence-floor two-source lineage and state-unallocated state-native semantic adapters remain deferred by #192. |
| Geography/grain | #190 COUNTY, SITE_EVENT, SOURCE_ONLY_COUNTY validation | Native site/event cannot become county evidence by attaching a county label; unresolved geography stays UNKNOWN. |
| Observation/event period | #190 typed time; #191 freshness | Cumulative through date, point date and period are distinct; clinical effective time needs reviewed aggregation. |
| Acquisition/revision | #190 immutable revision; #191 freshness; #193 artifact/run joins | V128 source-level update/retrieval times explicitly NULL; observation retrieval is separate. No inferred last-updated. |
| Transformation/method | #192 mapping; #193 exact transformation/result joins; V128 human methodology IDs | Transport decoding is not the scientific method. Clinical aggregation requires a new reviewed method. |
| Units/denominators | #190 meaning signature and #191 matching fields | Future laboratory quantities cannot be pooled without terminology/unit and denominator review. |
| Missingness/suppression/unavailable | #190 value states; #191 state envelopes | FHIR dataAbsentReason is not an automatic one-to-one Atlas state mapping; publisher NO_RECORDS never means absence. |
| Quality/representativeness/limitations | #191 references to owning quality/eligibility contracts; #193 exact proofs | An ancestry edge does not establish comparability or county representativeness. |
| Terminology/standards | Existing canonical IDs and versioned mapping registry | CDC MMG/PHIN VADS crosswalk belongs to #470; future FHIR laboratory contract to #472. No HL7/FHIR acquisition adapter exists in AdapterKind. |

## Representative delivered/gap matrix

The executable semantic contracts cover the first five source families below.
Coverage means validators and fixture examples exist, not that every live row
has been projected through them. Each family reuses the criteria above.

| Family | Existing mapping and evidence | Residual gap / bounded owner |
| --- | --- | --- |
| Human surveillance | `human_surveillance`: CDC `cdc_lyme`, dataset `x5j9-wybp`, resource `cdc_lyme_x5j9_wybp`, `case_count_floor_2023`; #192 tests and V128 human methods | #470 standards crosswalk; deferred incidence-floor/state-unallocated adapter coverage; no case-level message fields recoverable from published county floors. |
| County tick/pathogen | `county_tick_status`, `county_pathogen_status`; cumulative status and separate source/proof identities | Exact-source admission remains governed; no county absence claim from missing records. |
| Native tick/pathogen | `neon_collection`, `neon_pathogen_test`; site/event identity, canonical strata, normalization proofs | Site/event evidence is NOT_COUNTY_REPRESENTATIVE; no automatic county aggregation or release membership. |
| SVI/RUCC | `svi`, `rucc`; RPL_THEMES and RUCC_2023 preserve context vintage and native county grain | Context is not a clinical observation or laboratory signal; publication timestamps are not invented. |
| Environmental | `nclimgrid_prcp/tmin/tmax/tavg`, NLCD and MOD13Q1 registry entries; versioned measure JSON and dedicated tests | Definitions are candidates; DEV validation/public exposure remain separate (DATA443 PR #552 is now merged on refreshed main). Never imply county-release publication from registry membership. |

## Residual work and acceptance limits

Reuse #443/#496 ownership for representative real authority-snapshot replay
through #192/#193/#194 with reviewed #191 metadata, approved consumer-safe
lineage, reproducible redacted receipts, pinned revisions and negative join
tests. Real run/artifact rows alone do not meet these gates. Do not propose
another generic replay issue or ledger; ownership acceptance remains pending.
Source-specific: the proposed human follow-up covers only existing fixed-release
case-floor/SVI-denominator two-input lineage and native STATE unallocated
semantics with compatibility tests; preserve historical release rows and add
no historical denominator ingestion. These scopes are not implemented here.
#470 owns standards terminology; #472 owns future clinical aggregation,
denominator, effective-time, deduplication, privacy and authorization design.
DATA473 criterion 4 and DATA471 criterion 6 remain open until bounded follow-up
ownership is accepted. Checked-in drafts alone do not satisfy those criteria.

Current open-data output compatibility is preserved: no runtime code, source
configuration, SQL, grants, scoring, release pointer or public fields change.
Tests can prove contract reuse and negative invariants; they cannot establish
MMG/FHIR interoperability, runtime acceptance or access to clinical data.

Reproduce the existing evidence with:

```powershell
uv run pytest tests/test_semantic_domain.py tests/test_semantic_metadata.py tests/test_semantic_source_mappings.py tests/test_semantic_lineage.py tests/test_semantic_consumer.py tests/test_current_semantic_metadata_views.py tests/test_current_source_methodology_projection.py tests/test_climate_semantics.py tests/test_interoperability_audit.py
```
