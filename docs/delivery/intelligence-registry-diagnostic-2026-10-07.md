# Fixed protected DEV source prerequisite diagnostic

Extends the existing `diagnose_intelligence_dev` route, with no new workflow,
credential, arbitrary SQL input, role override or mutation. Its dedicated
migration-service identity, 50-second whole-process watchdog, 10-second statement
and 2-second queue limits remain; detached statements abort. The workflow requires
`expected_pending_json=[]` with every other diagnostic off and exits before
migration application. Accounting confirmation remains mandatory.

The three timestamp columns now match approved NOT NULL DDL. Grant-option
metadata must be an explicit recognized boolean; missing/unknown values cannot
pass the exact-privilege checks. Regression DESCRIBE rows derive from approved
minimum-access SQL and V135 rather than repeat diagnostic expectations.

Immediately after identity, fixed reads inspect only EID Expedited and NIH News Releases.
They precede object DESCRIBE so an unrelated object failure cannot discard critical
source evidence. Each returns at most two latest-version rows (four rows total);
DENSE_RANK preserves duplicate
latest detection. SQL suppresses documents exceeding 64KiB; pure validation
rejects invalid JSON/schema/duplicate keys, mismatched row/document source ID,
version or hash, exact endpoint/host, daily cadence and bounded limits, inferred
topics/geographies and missing approved trust/source review. No runtime-identity
store is invoked under the migration role.

Exact proof uses the existing code-reviewed pilot receipt set: a receipt pins
the actual version/checksum of an independently reviewed private source snapshot.
The complete source document and actual reviewer identities/timestamps remain in
the authorized private operator evidence; **never copy them into the public repository**.
The complete-document hash binds review references, rights and policy content,
rather than merely checking nonempty fields. Receipt decision matches the
snapshot's approval decision;
retention binding must match its access/use reference, with the decided raw30day
policy and an exact restricted artifact identifier independently admitted in
REVIEWED_RESTRICTED_ARTIFACT_POLICIES. False, lists, empty strings, arbitrary
identifiers and PUBLIC_SEVEN_YEAR cannot be accepted by a populated receipt.
No real restricted identifier has yet been admitted; the map remains empty.
Native policy must bind the same
source checksum and allow only conservative title/link/language/pubDate metadata.
No fixture version/hash is inserted. No candidate is populated by this PR.

Public reports retain only fixed target/source IDs, fixed reason codes and
booleans. Exact observed version/hash and documents remain transient in process;
the persisted exact reviewed candidate plus `exact_reviewed_source_matches=true`
is the proof route. Query errors produce UNKNOWN_QUERY_FAILED, empty successful
reads ABSENT, and duplicates DUPLICATE_LATEST. Partial safe results are emitted
incrementally; errors never expose Snowflake exception details. COMPLETE means
inspection completed, not acceptance: inspect per-source and object booleans.
REVIEWED_CANDIDATE_REQUIRED is **not discovery of an unknown hash/version**.
Before populating pins, obtain a genuine bounded private latest-row receipt through
an authorized owner evidence route, review the exact document privately and attach
the private reference to the parent handoff. This diagnostic does not export such
documents and no private discovery route is added or claimed available here.
No candidate is inferred from fixture values or reconstructed from public logs.
With empty code-reviewed receipts, no source can pass. Missing object visibility
remains unknown rather than physical absence.

This is review-only code. No live diagnostic, grant, DDL or feed request was made.
Parent reviews exact head/CI and private aggregate cost reconciliation before any
dispatch. Only the three already-approved grant statements may later execute,
after relevant genuine source-policy/registry and existing-object checks; never
rerun the canonical file containing DDL. Missing objects/registration require a
separate reviewed bounded remediation. DATA132/135 remain open: capture,
publication, repoll and intended-role readback are not delivered by this diagnostic.

## Grants-only gate and capture scope

`all_prerequisites_passed` is an aggregate inspection summary, **not the grants-only
gate**: NIH may remain blocked and approved grants may legitimately be missing.
For the EID-only proposal, require its exact source/policy proof plus verified
existing registry/retention tables and V2 target ownership, exact schemas/view
definition, and no unexpected target-role privileges or grant options. Missing
grant metadata remains unknown and blocks. Explicitly absent authorized privileges
on otherwise verified existing targets are the intended remediation, not grounds
to run DDL or broaden access. Legacy V1 findings remain separate consumer context.

Review the exact missing subset of the three authorized statements: runtime
SELECT/INSERT on retention documents, runtime INSERT on retention audit, reader
SELECT on V2. Skip statements already satisfied; never add grant option, privileges
or other targets. Execution remains parent-coordinated and outside this diagnostic.
Missing objects, wrong ownership/definition or missing policy registration require
separate bounded reviewed remediation; they cannot be repaired by granting access.

The private capture allocation covers **one acquisition-only attempt**. It does
not authorize a repoll, normalization, second feed or DATA135 acceptance expansion.
