# Current DEV cleanup ownership report proposal

This report is separate from the historical V143 pre-handoff verifier. It does
not require deployer ownership, one grant, the V143 body, or an empty attestation
table. That verifier remains unchanged.

The proposed `report_dev_cleanup_ownership` input uses the existing DEV migration
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
The existing DEV_OWNER role could not SHOW GRANTS on either object (002003).
This proposed existing-service route has not executed; its visibility remains
unverified. If it is denied, report the exact object and stop; do not add grants
or substitute a more privileged credential. Review and merge are required before
any main-only workflow dispatch; dispatch capability is not currently available
through the connected tool. Native environment gates remain applicable.
