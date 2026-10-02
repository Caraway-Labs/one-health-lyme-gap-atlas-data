# DATA377 offline comparison and acceptance limits

Expected outcomes were frozen at commit 3c81b47 before supporting artifacts.
Independent rubric review is pending. Baseline inspected: c5a2310.
Context, operation and handoff interfaces reuse DATA370/371/373/375; no duplicates
of snapshot or failure-evidence implementations are introduced.

| Historical case | Frozen requirement | Delivered observation | Assessment |
| --- | --- | --- | --- |
| #336 connector bulk writes | UNKNOWN without engine proof | Preflight without observed facts UNKNOWN | Engine semantics unverified; no preventive claim |
| #353 procedure binding | UNKNOWN without separate procedure proof | Preflight without observed facts UNKNOWN | Caller/owner invocation unverified |
| #365 canonical coverage | 2/3; one explicitly unknown, source-only unallocated | Deterministic set fixture preserves expected membership | Fixture arithmetic only; V098 engine behavior unverified |
| #366 runtime INSERT | BLOCKED runtime; separate UNKNOWN authority | Corrected contract checks SEMANTIC_RELEASES; denied fixture BLOCKED, authority UNKNOWN | Frozen expectation met offline; no live proof |
| Missing context | BLOCKED with missing path | Existing helper returns AGENTS.md for empty fixture | Offline reference helper proof |
| Stale context | UNKNOWN current readiness | No observed facts gives UNKNOWN | Actual stale-snapshot integration awaits DATA372 |

The authorized narrow contract correction now compares the denied #366 fixture
against its unchanged frozen BLOCKED expectation. Passing this offline comparison
does not establish historical prevention or actual protected-workflow identity.
No performance percentage or deterministic agent behavior claim.

DATA372 final snapshot schema/freshness/drift fixtures and DATA376 final sanitized
failure packet/correlation/redaction outputs must be integrated before capstone
acceptance. Their paths are pending, not invented. Separate owners should provide exact
heads, schema versions, fixture entrypoints and evidence classes to the parent.

Local verification uses locked uv dependencies. Live database execution, deployment,
and live functional proof remain UNKNOWN. Documentation and fixtures require no DB
migration or runtime release; parent coordinates independent review, refreshed main,
exact Quality CI and serialized existing deployment if needed.

## Current-contract diagnosis of #366

The inspected baseline had a genuine missing/mismapped desired-state permission
contract, not an expected-fail historical fixture. The fixed expectation remains
BLOCKED for a known denied SEMANTIC_RELEASES INSERT; the corrected contract returns
BLOCKED for that supplied fixture while invisible authority and identity stay UNKNOWN.

Evidence at baseline c5a2310:
- `src/lyme_gap_atlas_data/semantic_release.py`, `_insert_release`: current
  candidate assembly executes INSERT INTO PRESENTATION.SEMANTIC_RELEASES.
- `migrations/V099__semantic_release_protected_operator_grants.sql`: grants
  SELECT/INSERT/UPDATE on that table to OH_LYME_{ENV}_MIGRATION_DEPLOYER,
  plus only the other documented release-table actions.
- `config/operation-capabilities-v1.yml`: semantic_release maps executor owner,
  requirements V071/V072/V073 and GOVERNED_RELEASES:INSERT; it does not include
  the actual #366 table or V099 requirement.
- `.github/workflows/publish-semantic-release.yml`: protected workflow both
  applies migrations and runs semantic-release-build/publish/rollback through
  its configured identity. Its secret role value is not inspected or inferred.

Authorized correction: semantic_release now requires SEMANTIC_RELEASES:INSERT and
maps its desired protected executor to migration_deployer, supported by V071's
protected release-builder boundary, V099 and the protected migration/build workflow.
V099 is listed only under required_migrations_by_environment.prod, consistent with
PROD_ONLY_MIGRATION_VERSIONS and the production-only #366 correction. DEV retains
V071/V072/V073; no DEV V099 application is requested. Validation rejects a shared
or DEV-scoped PROD-only prerequisite. Desired mapping is not observed identity;
missing inspection or capability evidence remains UNKNOWN and cannot authorize work.
No grants, credentials, execution permissions or migration bytes changed. The
required_migrations plan output remains a resolved list for its explicit environment.

## Integration requirements for separate owners

DATA372 must supply exact reviewed head, public-safe snapshot schema/version,
normalization/hash and freshness rules, deterministic stale/hidden/inherited-grant
fixtures, and callable validator/comparison entrypoints. Integrate stale-context
against that interface; absent authorized observation stays UNKNOWN.

DATA376 must supply exact reviewed head, failure-packet schema/version, separate
workload/workflow/artifact identities, stable correlation rules, sanitized historical
packets and redaction/incomplete-evidence fixtures. Validate packet-to-regression
links without duplicating its collector. Keep offline, DEV execution, deployment,
and live proof separate. Final outputs and independent frozen-rubric review are
required before capstone acceptance.
