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
| #366 runtime INSERT | BLOCKED runtime; separate UNKNOWN authority | Contract checks GOVERNED_RELEASES, not historical SEMANTIC_RELEASES; UNKNOWN | Coverage gap; capstone not accepted |
| Missing context | BLOCKED with missing path | Existing helper returns AGENTS.md for empty fixture | Offline reference helper proof |
| Stale context | UNKNOWN current readiness | No observed facts gives UNKNOWN | Actual stale-snapshot integration awaits DATA372 |

The tests intentionally preserve the #366 gap rather than alter the curated contract
without its owner. Passing these tests validates comparison honesty, not complete
historical prevention. No performance percentage or deterministic agent behavior claim.

DATA372 final snapshot schema/freshness/drift fixtures and DATA376 final sanitized
failure packet/correlation/redaction outputs must be integrated before capstone
acceptance. Their paths are pending, not invented. Separate owners should provide exact
heads, schema versions, fixture entrypoints and evidence classes to the parent.

Local verification uses locked uv dependencies. Live database execution, deployment,
and live functional proof remain UNKNOWN. Documentation and fixtures require no DB
migration or runtime release; parent coordinates independent review, refreshed main,
exact Quality CI and serialized existing deployment if needed.

## Current-contract diagnosis of #366

This is a genuine missing/mismapped desired-state permission contract, not an
expected-fail historical fixture. The fixed expectation remains BLOCKED for a
known denied SEMANTIC_RELEASES INSERT; comparison remains UNKNOWN until the
curated contract covers the actual boundary.

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

Contract-owner follow-up: reconcile curated operation identity/dependencies and
bounded runtime table capabilities with V099 and current release commands; retain
separate grant authority and bootstrap findings, review DEV/PROD applicability,
and add behavioral comparisons against the frozen corpus. Do not add a grant or
edit historical migration bytes. This contribution changes none of those surfaces.

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
