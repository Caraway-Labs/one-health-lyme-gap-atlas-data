# DATA #132/#135 EID Expedited DEV remediation checkpoint

This follow-up starts from `origin/main` at `0765061e7ec16c44e4af6cec4a118169225cfa6f`.
The protected read-only DEV run [37624314644](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/37624314644)
completed with no writes. The EID and NIH registry rows were `ABSENT`.
`INTELLIGENCE_SOURCE_VERSIONS` matched its expected shape, owner, and grants.
The two raw-retention tables and `INTELLIGENCE_FEED_V2` were not visible, which
does not prove physical absence. The existing V1 view was visible but its
definition did not match the reviewed version filter.

This change adds only the EID SourceDefinition, selects EID in the existing
bounded runtime/workflow path instead of deferred Vital Signs, and adds an exact
direct `DESCRIBE` check to the protected migration-identity diagnostic. A
successful direct describe proves an object exists even if `SHOW` omitted it;
a failed describe leaves physical state unknown. Neither result alone qualifies
the expected owner, shape, grants, or view definition. No source or policy
receipt is added to the executable receipt set.

## Conditional forward-only DEV delta

The following statements are the *maximum candidates*, not an executable
batch. Select only after direct object evidence and an independently reviewed
diff. No V-number is allocated while physical presence is unresolved.

1. If genuinely absent, create exactly `GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS`
   and `GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT` with the reviewed column
   shapes in `docs/contracts/intelligence/v2/raw-runtime-schema-review.sql`.
   Grant the existing DEV runtime role only `SELECT, INSERT` on documents and
   `INSERT` on audit. Do not recreate or replace a visible but mismatched table.
2. Replace the existing `PRESENTATION.INTELLIGENCE_FEED_V` with the reviewed
   `contract_version='1.0.0'` filter using `COPY GRANTS`. Create V2 only if
   absent, with the reviewed `contract_version='2.0.0'` projection from
   `docs/contracts/intelligence/v2/presentation-projection.sql`; grant the
   existing DEV read role `SELECT` on V2. An existing mismatched V2 requires
   a separate exact-definition review before replacement.
3. Raw-copy expiry remains an additional requirement: the reviewed cleanup
   approvals/procedure and least-privilege owner path in
   `raw-runtime-schema-review.sql` must be verified or delivered before a
   capture that promises 30-day deletion. No direct runtime `DELETE` grant.

The source document must retain the exact approved endpoint, daily cadence,
bounded one-request limits, no inferred topic/geography, metadata-only rights,
and a real source-specific retention and technical review reference. PR #631's
candidate is nonexecutable: its registry version/hash and policy/reviewer fields
remain null. A historical fixture version or checksum is not a live registry
allocation. The source record, source-specific native policy, restricted artifact
policy, and checked-in runtime receipt must be reviewed as one pinned set before
owner registration. `config/intelligence/pilot-policy-receipts.json` remains
empty. The current diagnostic must then pass EID and all relevant objects on the
actual deployed commit before one acquisition-only DEV attempt. NIH can remain
blocked; it is not an EID gate.

No migration, grant, source registration, feed request, normalization, or load
is authorized by this document itself. Keep both issues open until their actual
acceptance evidence exists.
