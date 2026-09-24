# Story #195 completion matrix

| #195 acceptance criterion | Governance artifact/code | Test/evidence | Status |
| --- | --- | --- | --- |
| Executable IDs/cardinalities, types, units, denominators, geography/time/strata, states, metadata, lineage, evidence and transitions | Existing #190–#193 validators composed by `semantic_governance.py` | `test_semantic_domain.py`, `test_semantic_metadata.py`, `test_semantic_lineage.py`, `test_semantic_source_mappings.py`, `test_semantic_governance.py` | COMPLETE for fixture/code contracts |
| Immutable published county baseline | `county-release-v1.json`; governance contract | `test_frozen_county_release_slots_and_meaning` | COMPLETE as contract fixture; no PROD audit claim |
| Multi-shape county/site-event/derived/source-only, incompatible denominators, states, duplicate/orphan cases | Existing #190–#193 fixtures plus #195 transition cases | Normal pytest suite, focused governance suite | COMPLETE for synthetic fixtures |
| Generated checks from governed registries | #192 registry and existing tick registry tests; #195 mapping parameterization | One generated identity/vintage case per registry entry; normal suite exercises tick registry | COMPLETE for current registries |
| Changed connector/procedure/role/storage behavior in real Snowflake | No such behavior changed | No DB integration asserted | NOT APPLICABLE |
| Candidate failure, pointer, idempotency, publication, immutable history, #194 compatibility | Existing release validator and tests; frozen current output contract | `test_semantic_release.py`, `test_publish_semantic_release_workflow.py`, #195 failed-candidate pointer test and release baseline | COMPLETE for code/fixture boundary; #194 future output remains #194 |
| CI separates fixture/integration/protected/live evidence | Normal Quality pytest job; governance contract evidence section | Hosted Quality after PR | PENDING hosted Quality |
| Versioning/deprecation and owning remediation path | `atlas-semantic-governance-v1.md`, `semantic_governance.py` | Transition and removal tests | COMPLETE for #195 |
| No weaker permissions or history/Alpha/restricted access | Python/contracts/tests only | Diff review; no migration, workflow or API edits | PENDING final diff review |

Story #194 owns machine-readable consumer/public representation, API and generated-client changes, live consumer tests, and migration execution. No #194 implementation is included here.
