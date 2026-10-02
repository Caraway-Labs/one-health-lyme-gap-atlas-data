# Bounded Snowflake metadata evidence v1

Owner: data repository. Parent #369, story #372; consumers #374, #376, #377.
Contract: `docs/contracts/snowflake-snapshots/v1.schema.json`.
Reviewed publication scope: `config/metadata-scope-v1.json`.

Dependencies #370/#371 closed through #379. Their actual desired contract is
`config/operation-capabilities-v1.yml`: four operation capabilities and four
role aliases. It is not a comprehensive desired schema. This exporter compares
those capabilities; column/procedure observations and baseline changes are
separate evidence, not invented desired scientific or product requirements.

The initial scope covers the four operation objects and explicitly listed key
columns. The county view's presence/kind is its safe signature; its definition
and columns are omitted. Column types, nullability, position and numeric/length
metadata are projected only for reviewed columns. Owners and grants use role
aliases. Unknown owner names are represented as `unknown`. No account, host,
warehouse, user, personal path, body, comment, row payload, SQL literal, prompt,
private key or credential is emitted. Raw metadata never becomes an output file.
Adding identifiers or procedure signatures requires code review of the scope.
Default procedure scope is empty. Optional reviewed signatures use only safe
literal-free argument types; DESCRIBE output is filtered server-side using a
pipe query to return only `returns` and `execute as`, never a body.

## Evidence semantics

Live inspection is DEV only, using existing named `ATLAS_DEV_READ`, with exact
role/database validation before collection. No browser login, role switch,
administrator fallback, new credentials/grants, DDL/DML or automatic remediation.
PROD remains unverified by this DEV-only exporter. The existing documented
`ATLAS_PROD_RUNTIME_AUDIT` route requires separate explicit audit authorization;
this implementation does not use it or expand its access. Measure metadata,
exact publication tuples and lineage receipts are outside this curated scope.
Timeouts, errors and malformed responses use fixed redacted diagnostics.
Each CLI query uses an independent named primary-role session. Sampling is
non-atomic; grants and visibility may change during capture. `generated_at` is
UTC capture completion, never proof that observed access continues afterward.

Visibility is always `partial` for live export. Information Schema and SHOW
results are role filtered: an empty result means unknown, never absence. Direct
grants and observed role edges among the four aliases can prove a bounded
positive capability; missing direct grants cannot disprove effective inherited
access. PUBLIC, secondary roles, database roles, legacy child roles and all
unallowlisted hierarchy remain uninspected. Future grants are restricted to the
reviewed schemas and recognized object-kind placeholders; they describe future
policy, not current object access. Out-of-contract visible grants are
`unexpected` evidence, not a conclusion that they violate policy.

Reports distinguish `mismatched`, `unexpected`, `stale`, `unknown`, and
`missing`. A successful complete migration-ledger SELECT can establish a missing
required migration row. Role-filtered object/grant results cannot establish
absence and produce `unknown`. Baseline removals similarly remain unknown.
No snapshot can produce readiness PASS or authorize a consequential operation.
Ledger checks accept LF/CRLF-equivalent migration hashes. Other checksum changes
are unknown until approved legacy reconciliation evidence is inspected; this
export does not claim they are unauthorized historical edits. An old or
unreviewed scope is rejected as incomparable without echoing arbitrary fields.
The baseline must have identical environment and scope; changed columns or
procedure execution mode produce a mismatch against the previous observation.

Default maximum age is 24 hours in the reviewed scope; shorten it by reviewed
policy when needed. Reports check age, future timestamps, content integrity and
current contract/scope hashes. Revalidate identity, capabilities, migrations and
approval live immediately before consequential plans or actions even within TTL.
`semantic_hash` covers normalized content plus stable environment, scope,
contract, visibility, source class, ledger completeness and unavailable categories.
Timestamps and code commit are envelope provenance and do not change it.
Contract/scope hashes are also exposed separately.

## Manual refresh and publication

```text
uv run atlas-data metadata snapshot --code-commit <full-reviewed-head>
uv run atlas-data metadata report --snapshot .atlas-metadata-private/snapshot.json
uv run python scripts/verify_metadata_snapshot_dev.py
```

Supply the exact Git head executing the exporter. The CLI verifies HEAD and a
clean tracked checkout before collection. Live export requires a local Git
checkout; an image without Git provenance can still validate/report snapshots.
The snapshot command stages sanitized JSON and machine/human reports under the
ignored `.atlas-metadata-private/` directory. It never publishes. Inspect source
comparison, scope/omissions, redaction tests, UTC capture time, role and full
code head; then an explicitly reviewed publication may copy sanitized artifacts
into proposed `docs/generated/snowflake/`. Restricted identifiers stay in an
approved private artifact, referenced by a safe opaque evidence ID in review
notes; do not commit internal paths or raw source responses. Fixture examples
are labeled synthetic and are not live DEV/PROD evidence.

Protected CI refresh proposal: manual dispatch at a reviewed exact SHA, using
an existing separately approved least-privilege audit identity in protected DEV
or PROD environment; fail closed on identity/visibility gaps, stage private
artifacts, run sanitization/source comparison and obtain review before any
public artifact commit. Do not attach raw metadata or diagnostics to public CI
logs/artifacts. Untrusted PR checks run fixtures only and obtain no production
credentials. No workflow or credential changes are part of this story.

Snowflake references reviewed for this implementation:
[SHOW GRANTS](https://docs.snowflake.com/en/sql-reference/sql/show-grants),
[Information Schema](https://docs.snowflake.com/en/sql-reference/info-schema),
[DESCRIBE PROCEDURE](https://docs.snowflake.com/en/sql-reference/sql/desc-procedure).
