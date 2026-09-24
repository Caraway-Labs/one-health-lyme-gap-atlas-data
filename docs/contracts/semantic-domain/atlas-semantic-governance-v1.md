# Atlas semantic governance v1

Status: Story #195 implementation candidate. Owner: Atlas data stewardship and engineering. Authority: `atlas-semantic-domain-v1`, ADR 0035, `atlas-semantic-metadata-v1`, `atlas-semantic-lineage-v1`, `atlas-semantic-source-mappings-v1`, the fixed semantic-release contract, and owning #157–#159 contracts. Executable checks: `semantic_governance.py`, existing domain/metadata/lineage/mapping/release validators, and the normal Quality pytest suite. The invariant inventory is `story-195-governance-invariant-matrix-2026-09-24.md`.

## Transition actions

| Change | Executable outcome | Required action |
| --- | --- | --- |
| Display text, example, formatting or documentation only | `IDENTICAL` measure meaning | Patch documentation; metadata object edits require an immutable metadata revision. |
| Compatible explanatory metadata or safe additional limitation detail | `COMPATIBLE` metadata revision | Increment metadata revision, retain measure ID/version and prior revision, obtain review when interpretation limitations change. |
| New measure | New identity | Assign reviewed measure ID/version and complete metadata/mapping/lineage as applicable. |
| New optional governed stratum | `COMPATIBLE` extension | Add to canonical stratum registry, review applicability, increment minor semantic version, retain old version. Unknown strata fail. |
| New exact-source mapping with unchanged measure meaning | New mapping identity | Prove exact source eligibility and reviewed metadata/lineage under #192 before use. A changed source vintage is a new immutable input revision. |
| Changed unit, denominator, geography, time, value interpretation, scientific definition or comparability | `REQUIRES_NEW_SEMANTIC_VERSION` or `INCOMPATIBLE` | Review new major measure semantic version or new identity and consumer migration. A same-version edit fails closed. A new version alone never proves scientific comparability. |
| New source evidence, transformation, evidence basis, input set or result payload | `REQUIRES_NEW_REVISION` or `NOT_COMPARABLE` | Retain prior observation/result and lineage; derive a new immutable identity/revision under the owning contract. Reordered inputs preserve identity. |
| Consumer-visible publication set or methodology | New release | Build a new source-pinned candidate and use existing protected publish gate. Never edit historical release or move current pointer on candidate failure. |

`compare_measure`, `compare_metadata`, `compare_mapping`, `compare_revision`, `compare_lineage`, and `compare_release` return explicit outcomes and reason codes. `require_measure_transition`, `validate_mapping_transition`, and `validate_cross_contract` reject invalid transitions and missing references. Callers must validate complete candidate shapes with the owning validators; comparison never authorizes source ingestion, source comparability, public projection, or publication. If owning contracts disagree, the candidate fails rather than choosing one.

## Deprecation

A machine-readable deprecation record has stable `identity`, `kind`, `state: DEPRECATED`, `effective_semantic_version`, `replacement_identity` (nullable when none exists), and nonempty `migration_expectation`. The old definition, metadata revisions, lineage and release remain addressable and immutable. Removing a required mapping without a deprecation record fails `MAPPING_REMOVAL_UNDECLARED`. A deprecation is a reviewed consumer migration instruction, not permission to rewrite old rows. #194 owns consumer exposure and migration implementation.

## Release and evidence boundary

`tests/fixtures/semantic_governance/county-release-v1.json` freezes the published five source slots, 14 physical observation slots, type/unit/grain/time meanings, county count, schema and transformation version, and historical incidence/state-unallocated exceptions. The physical `geometry` observation versus `county_geometry` hierarchy identity remains explicit. The fixture is a contract snapshot, not a PROD audit. The incumbent semantic-release tests cover candidate rollback, pointer stability, publication prerequisites and idempotency. This story changes no SQL, connector, procedure, roles, storage, pointer or public view. Its tests provide fixture/unit evidence; hosted Quality supplies container validation. No new Snowflake or live-consumer claim is made.
