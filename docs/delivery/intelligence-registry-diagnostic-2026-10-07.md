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

After object checks, fixed reads inspect only EID Expedited and NIH News Releases.
Each returns at most two latest-version rows; DENSE_RANK preserves duplicate
latest detection. SQL suppresses documents exceeding 64KiB; pure validation
rejects invalid JSON/schema/duplicate keys, mismatched row/document source ID,
version or hash, exact endpoint/host, daily cadence and bounded limits, inferred
topics/geographies and missing approved trust/source review. No runtime-identity
store is invoked under the migration role.

Exact proof uses the existing code-reviewed pilot receipt set: a receipt must
contain the complete `reviewed_source_document` and its actual version/checksum.
All source review identities/times/references, rights conditions and policy
references therefore match the independently reviewed snapshot, not merely
nonempty fields. Receipt decision matches that snapshot's approval decision;
retention binding must match its access/use reference, with the decided raw30day
policy and explicit reviewed artifact class. Native policy must bind the same
source checksum and allow only conservative title/link/language/pubDate metadata.
No fixture version/hash is inserted. No candidate is populated by this PR.

Public reports retain only fixed target/source IDs, fixed reason codes and
booleans. Exact observed version/hash and documents remain transient in process;
the persisted exact reviewed candidate plus `exact_reviewed_source_matches=true`
is the proof route. Query errors produce UNKNOWN_QUERY_FAILED, empty successful
reads ABSENT, and duplicates DUPLICATE_LATEST. Partial safe results are emitted
incrementally; errors never expose Snowflake exception details. COMPLETE means
inspection completed, not acceptance: inspect per-source and object booleans.
With empty code-reviewed receipts, no source can pass. Missing object visibility
remains unknown rather than physical absence.

This is review-only code. No live diagnostic, grant, DDL or feed request was made.
Parent reviews exact head/CI and private aggregate cost reconciliation before any
dispatch. Only the three already-approved grant statements may later execute,
after relevant genuine source-policy/registry and existing-object checks; never
rerun the canonical file containing DDL. Missing objects/registration require a
separate reviewed bounded remediation. DATA132/135 remain open: capture,
publication, repoll and intended-role readback are not delivered by this diagnostic.
