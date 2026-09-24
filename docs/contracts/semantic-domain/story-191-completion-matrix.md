# Story #191 acceptance matrix

Baseline: fetched `origin/main` `94de76acf2bebc7b7a826919e9c7d89fdf11600d` on 2026-09-24, exact Story #190 merge. This table distinguishes #191 contract/fixture proof from later mapping, database, and consumer work.

| #191 acceptance requirement | Artifact | Test/evidence | Status |
| --- | --- | --- | --- |
| Inventory actual fields against #190 | `story-191-metadata-gap-matrix-2026-09-24.md` | Field/authority/classification/owner audit against V071/V072, #157–#159, #190 | Completed in #191 |
| Versioned metadata for semantics, applicability, provenance, freshness, quality, restrictions and limitations | `atlas-semantic-metadata-v1.md`; `semantic_metadata.py` | Nine checked-in metadata fixtures and validator tests | Completed as contract and fixture proof; #192 owns exact source mappings, #193 owns lineage joins |
| Distinguish source-reported, steward-reviewed, governed-generated, non-authoritative generated summary | Contract authority section; `authority` fields | Authority and generated-summary negative tests | Completed in #191; actual stewardship remains a human decision |
| Stable metadata IDs/revisions; explicit UNKNOWN / NOT_APPLICABLE / UNAVAILABLE | Deterministic attachment/revision functions and state envelopes | Label/description stability, definition/meaning, state, duplicate/gap tests | Completed in #191; #195 owns cross-release compatibility matrices |
| Reuse quality components and #158/#159 limits/evidence | Typed `quality_evidence` references and limitation codes | Quality/eligibility composition and required-limitation tests | Completed by reference; owning contracts still validate their own payloads |
| Reject contradictory unit/denominator/applicability, missing provenance, stale/unapproved references and unversioned meaning | `validate_metadata` and `validate_metadata_revisions` | Focused negative tests; optional governed source-version allowlist | Completed for definition/fixture validation; #192/#195 own runtime source and cross-release proof |
| Preserve current county release metadata compatibility | No builder, V071/V072, pointer, public-view or migration changes | County source-slot/count regression test; full repository suite and diff gate | Completed at code/fixture level; no database replay claimed |
| Safe examples for human, SVI, RUCC, tick/pathogen, NEON collection/testing, derived result | `examples/story-191-safe-metadata-fixtures.json` | Checked-in examples compared to validated generated fixtures | Completed synthetic examples only; source-backed mapping belongs to #192 |
| Safe/public excludes restricted material and unsupported interpretation | `visibility`, safe-value validation, limitation rules | Restricted key, URL, path, credential, internal-derived tests | Completed metadata validation; #194 owns actual public/API projection and consumer proof |

No database schema, connector, release builder, public view, or API was changed. There is no new Snowflake integration or live consumer evidence to claim. Hosted Quality is the container gate where local Docker is unavailable. The parent Epic #188 remains open for #192–#195.
