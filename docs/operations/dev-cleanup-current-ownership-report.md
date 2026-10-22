# Current DEV cleanup ownership report proposal

This report is separate from the historical V143 pre-handoff verifier. It does
not require deployer ownership, one grant, the V143 body, or an empty attestation
table. That verifier remains unchanged.

The `report_dev_cleanup_ownership` input uses the existing DEV migration
service connection, on main only. All other dispatch inputs must be disabled or
empty. Validation runs before credential materialization; fixture/recovery jobs
are excluded when report mode is selected. Report mode exits before deployment,
registration, migration, handoff, or cleanup branches.

Only these statements are allowlisted:

1. Current user, role, database, and warehouse identity.
2. SHOW GRANTS ON PROCEDURE
   ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR).
3. SHOW GRANTS ON VIEW
   ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V.

Each object reports the observed owner and role grants, including grant option.
Unexpected owners are observations, not failures against a presumed handoff.
Missing, incomplete, oversized, denied, or ambiguous metadata remains UNKNOWN.
An independent readable object is still reported if the other fails. Provider
errors are sanitized. No object bodies, feed rows, keys, or attestation rows are
printed. Each query has a 15-second limit, a 1 MiB JSON/64-row response limit,
and the process has a 60-second watchdog. Responses exceeding bounds are rejected.

No grants, ownership changes, migration, purge, or source capture are included.
A PARTIAL result leaves visibility unresolved; a successful view read does not
establish procedure visibility. For denied or unavailable metadata, report the
exact object and stop; do not add grants or substitute a more privileged
credential. Changes require review and merge before execution through the
main-only workflow. Native environment gates remain applicable.

The diagnostic refinement keeps the same three statements and identity. Failures
include a validated six-digit Snowflake error code, five-character SQLSTATE, and
UUID query ID where the CLI supplies them. Provider messages, SQL text, command
arguments, stdout/stderr, and unrelated JSON fields are never copied into the
report. Only fixed explanations are emitted. In particular, 002003 remains
ambiguous between an absent object and insufficient visibility; it cannot justify
granting access. Timeout, invalid JSON, excessive response size, malformed rows,
and local CLI failures are classified separately from database errors.

For a valid, unambiguous observed owner only, `owner_matches_expected` records
explicit equality against the documented migration-deployer and purge-owner
roles. Missing, masked, ambiguous, or invalid metadata yields null comparisons.
This does not recover or infer any value hidden by GitHub masking. Runtime
verification must still use the reviewed workflow under the same existing role;
this refinement does not run queries or alter access.
