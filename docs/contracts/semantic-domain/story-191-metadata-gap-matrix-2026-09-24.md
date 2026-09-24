# Story #191 semantic metadata gap matrix

Audited fetched `origin/main` at `94de76acf2bebc7b7a826919e9c7d89fdf11600d` on 2026-09-24. No commits followed the #190 merge. This matrix describes the contract gap before implementation; it does not assert database or consumer integration.

| Metadata concept | Existing field/contract | Authority | Classification | Gap | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Metadata identity | `measure_id`, `semantic_version` | #190 domain v1 | EXTEND COMPATIBLY | Attach metadata revision without another measure ID | #191 |
| Metadata version/revision | #190 meaning signature and version transitions | #190 domain v1 | NEW VERSIONED CONTRACT | Stable content revision and transition classification | #191; #195 cross-release gates |
| Display label | V071 measure label; #190 excludes label from meaning signature | V071, #190 | DELIVERED / REUSE | Govern revisions separately | #191 |
| Scientific definition | #190 measure `definition`; V071 methodology/description | #190 | EXTEND COMPATIBLY | Mandatory reviewed meaning and wording change rules | #191 |
| Unit | V071 measure unit; #190 measure unit | #190 | DELIVERED / REUSE | Verify metadata agrees with measure | #191 |
| Denominator | #190 explicit denominator; #158 M1/M2 denominators | #190, #158 | DELIVERED / REUSE | Verify metadata agrees; `NONE` explicit | #191 |
| Geography applicability | #190 `COUNTY`, `SITE_EVENT`, `SOURCE_ONLY_COUNTY` | #190 | EXTEND COMPATIBLY | Govern applicable grain and representativeness reference | #191; #192 mappings |
| Temporal applicability | #190 period/point/cumulative semantics | #190 | EXTEND COMPATIBLY | Govern applicability separately from vintage/retrieval | #191; #192 mappings |
| Strata applicability | #190 canonical allowed strata | #190 | EXTEND COMPATIBLY | Require exact agreement and applicability states | #191; #192 mappings |
| Reported/derived applicability | #190 origin; separate V100–V102 derived stores | #190, #158/#159 | DELIVERED / REUSE | Reference origin; retain internal derived boundary | #191; #194 exposure |
| Publisher/source | Manifest `source_id`, label, URL; source gate | Semantic release | EXTEND COMPATIBLY | Safe attribution and conditional source reference | #191; #192 exact mapping |
| Source version/vintage | Manifest source version/vintage; #159 exact tuple | Semantic release, #159 | EXTEND COMPATIBLY | Keep vintage distinct; reject missing/unsupported version reference | #191; #192 mapping |
| Transformation/method | Release methodology and transformation; #158/#159 versions | Semantic release, #158/#159 | EXTEND COMPATIBLY | Typed method reference agreeing with #190 | #191; #193 chain |
| Quality | #157 component profile and #166 propagation | #157/#166 | DELIVERED / REUSE | Reference owning profile only; no composite score | #191 |
| Uncertainty | #157 component limitations; #158 unavailable reasons | #157/#158 | EXTEND COMPATIBLY | Explicit known/unknown/not-applicable/unavailable reference | #191 |
| Scientific eligibility | #159 exact-source attestation and tuple registry | #159 | DELIVERED / REUSE | Conditional reference, never generic approval | #191; #192 source proof |
| Representativeness | `NOT_COUNTY_REPRESENTATIVE`; county-native/source-only states | #190, #157/#159 | DELIVERED / REUSE | Carry exact state and limitation | #191 |
| Freshness | Observation time, vintage, retrieval; release generated/loaded times; #157 freshness component | #190, V071, #157 | NEW VERSIONED CONTRACT | Distinguish all dates and explicit absence states; no threshold | #191 |
| Use restrictions | Release/measure limitations; source permissions | V071, source governance | NEW VERSIONED CONTRACT | Machine-readable restriction codes, no permission expansion | #191; #194 projection |
| Interpretation limitations | V071 text; #157/#166 reason codes; #158/#159 limitations | V071, #157–#159 | EXTEND COMPATIBLY | Typed categories and required limits by shape | #191 |
| Provenance references | Source/version/run/artifact/retrieval in release and #190 | #190, V071 | EXTEND COMPATIBLY | Safe reference only; no parallel lineage ledger | #191; #193 edges |
| Evidence basis | #158/#159 immutable result basis | #158/#159 | DELIVERED / REUSE | Conditional reference for derived shapes | #191; #193 lineage |
| Consumer-safe visibility | #166 safe serialization; #158/#159 internal results; V072 public views | #166, #158/#159, V072 | NEW VERSIONED CONTRACT | Validate safe metadata envelope; no publication grant | #191; #194 consumer/API |
| Steward-review state | Source approval and proposed ADR 0035 | Source governance, ADR 0035 | NEW VERSIONED CONTRACT | Distinguish source-reported/reviewed/generated text and revision review | #191; steward decision |

No new Snowflake metadata table is needed for #191: versioned definitions and validation can attach to #190 identities while V071/V072 and V100–V102 retain their existing storage. Comprehensive source mapping, lineage joins, public projection, and cross-release compatibility belong to #192–#195 respectively.
