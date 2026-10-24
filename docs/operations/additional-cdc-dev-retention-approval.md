# V166 DEV cleanup extension: exact approval packet

Preparation only. Reservation: DATA #727. Companion ingestion: #724.
Matthew's 2026-10-22 01:17 decision approves the two source policies, publisher
descriptions/category retention and US$5/four sequential DEV capture/repoll runs.
This packet requests separate consequential migration/security/deployment
approval; it does not request that source or budget decision again.

## Prepared change

V166__dev_additional_cdc_feed_cleanup.sql replaces only DEV's existing
GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)
and INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V. It follows the existing V163
single-source exact-plan implementation, adapted to DEV and exactly
`cdc-eid-expedited`, `cdc-mmwr`, `cdc-newsroom`. It does not edit V143 or any
PROD SQL. Python and the DEV CLI accept one of those source IDs per plan;
EID remains the default. Other sources, mixed-source plans, wrong environments,
changed plans and normalized-data targets remain rejected.

Immutable capture+30-day expiry, cross-claim live-copy protection, exact canonical
plan/copy/lease/run hashes, independent plan approval, write guard, append-only
pending/outcome audit and already-absent semantics are preserved. The executor
receives no direct DELETE. No plan is approved and no deletion is performed by
the migration. No schedule, service user, credential or role is added.

Review5608497093 caught an unapproved PROD 48-hour threshold in the initial
preparation before deployment. The corrected DEV SQL requires expiry at or
before CURRENT_TIMESTAMP and blocks any shared claim expiring after now. The
old migration/body hashes are superseded; no early DEV cleanup is authorized.

Migration SHA256:
`a7f4a88238b631283d5a1db3dc2dc3bd6f234d1ce8e17d7a6277b94494dac91a`

Procedure body SHA256:
`0bb15e8c6e0baa89f66dd24d260534a20aa26a7e6870a3abb023d1c48087a097`

## Exact approvals before execution

Live current owners are **not yet verified** by the available role-filtered
metadata. The following is the expected V143 state and the exact proposed
transition; SECURITYADMIN/migration-owner readback must confirm it before any
ownership or grant statement. Stop on a different owner, overload or grantee.

| Fully qualified DEV object | Expected current owner (unverified) | Temporary owner | Final owner |
| --- | --- | --- | --- |
| ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR) | OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER | OH_LYME_DEV_MIGRATION_DEPLOYER | OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER |
| ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V | OH_LYME_DEV_MIGRATION_DEPLOYER | OH_LYME_DEV_MIGRATION_DEPLOYER | OH_LYME_DEV_MIGRATION_DEPLOYER |

REVOKE CURRENT GRANTS removes executor procedure USAGE during preparation;
CREATE OR REPLACE does not copy grants. Final procedure grants must be exactly
OWNERSHIP to the purge-owner and USAGE to
OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP, with no executor grant option or other
grantee. V166 restores SELECT on the expected-handoff view to the existing
purge-owner. The handoff appends one independently approved row to
ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS;
that table's owner/grants do not change.

Pause duration has not been measured: it is the staffed window from preparation
through V166, verified handoff/attestation and compatible runtime deployment.
The bounded migration invocation does not bound human handoff or recovery time.
Throughout that window all DEV raw cleanup, including EID, remains unavailable.
No PROD job, published/normalized article or API read is changed by these steps.

No broader role/table privilege, direct executor DELETE, grant option, user,
credential or purge-owner role assignment is introduced. There **is** a
persistent source-scope expansion of the existing owner-rights procedure to
MMWR/Newsroom, still restricted to one approved expired-copy plan at a time.
Restoring the same executor USAGE does not make that scope expansion temporary.

1. **Code review/merge:** approve this PR's exact current head after quality and
   independent review. Merge alone does not run migration, cleanup or ingestion.
2. **DEV security preparation:** an independently authorized SECURITYADMIN
   operator verifies V143's current physical procedure, view, owners, grants,
   ledger/body and existing dependencies, then follows
   `docs/contracts/intelligence/v2/dev-additional-feed-cleanup-owner-preparation-review.sql`.
   Transfer OWNERSHIP of only the four-argument DEV procedure and expected-handoff
   view to OH_LYME_DEV_MIGRATION_DEPLOYER with REVOKE CURRENT GRANTS. This closes
   existing DEV cleanup, including EID, during the coordinated maintenance window.
   No purge-owner assignment, broad migrator grant or credential expansion.
3. **Protected DEV migration:** after accounting/capability preflight, authorize
   existing `.github/workflows/deploy-dev.yml` at the exact reviewed green main
   SHA, environment dev, with only the following expected pending array:

   ```json
   [{"version":"V166","filename":"V166__dev_additional_cdc_feed_cleanup.sql","sha256":"a7f4a88238b631283d5a1db3dc2dc3bd6f234d1ce8e17d7a6277b94494dac91a"}]
   ```

   All diagnostic/registration/fixture modes stay false. The protected batch is
   exact and alone; do not append unrelated pending migrations. Existing
   feed_preflight_accounting_confirmed is a private reconciliation gate whose
   workflow text refers to an older US$8 package. Do not attest that older
   allowance or silently borrow it. Confirm this new operation's cost coverage
   and the exact workflow accounting binding before dispatch; this PR makes no
   workflow/credential changes. Native environment approval remains human-only.
4. **DEV security handoff:** after exact ledger/body readback, authorize
   `dev-additional-feed-cleanup-owner-handoff-review.sql`. Transfer only the
   procedure to OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER, restore only executor
   USAGE to OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP, and insert exactly one reviewed
   immutable attestation binding the above hashes to the physical created_on.
   A real HANDOFF_REF is required; the template placeholder is not approval.
   V166 restores only the existing expected-view SELECT dependency for the
   purge-owner. Any missing underlying grant is a separate exact request,
   never permission to replay the original security bootstrap.
5. **DEV image deployment:** coordinate existing app
   b33dbae7-e243-4e27-b3ca-1018f5897f87 via quality.yml deploy_dev=true after the
   reviewed immutable image is built and the attestation exists. The new Python
   gate requires V166 and cannot run against a stale V143 handoff. Verify with
   the actual cleanup service; no READ-role substitute. Check other sessions
   before changing this shared DEV app. No production app/job is in scope.
6. **Any future purge:** each source still needs its separate exact private
   inventory/plan checksum and independent plan approval. This packet does not
   approve deleting future expired raw copies. Source-specific Spaces delete
   coverage must be verified using existing approved access. A new credential
   or expanded permission requires its own concrete approval.

## Recovery and consequences

Snowflake DDL is nontransactional. If preparation or V166 fails, cleanup remains
closed; inventory owner, grants, physical body/created_on and ledger before any
retry. Do not rerun V143 or rewrite applied history. If V166 is recorded but
handoff fails, retry only the missing reviewed transfer/grant/attestation phase
after readback. Never insert a duplicate attestation. Any code rollback that
expects V143 must keep cleanup disabled; a restored SQL definition requires a
new reviewed forward migration and fresh attestation. No normalized records,
published content or existing capture provenance are deleted by deployment.

## Current evidence and limits

Live DEV V069/V135/V142/V143 hashes were verified in the companion work. Existing
DEV read/owner metadata is insufficient for full intelligence/cleanup capability
proof; no missing grant is inferred solely from hidden SHOW rows. A later bounded
read confirmed the existing ingestion warehouse is X-Small, running=0, queued=0,
auto-suspend=60 seconds, with no visible resource monitor. Two-hour metering
returned zero windows and NULL aggregate credits: this is unavailable/latent
accounting, not proof of zero spend or US$5 headroom. No dollar conversion or
private accounting confirmation is fabricated. Capture/repoll runs used: 0/4;
new feed requests: 0. No LLM work, no new key and no purge occurred.

Offline tests are synthetic and cannot establish Snowflake stored-procedure
semantics, actual service privileges, key source coverage or cleanup handoff.
Those remain explicit execution gates. The actual API-reader console limitation
and supported browser-console handoff remain unchanged; no access bypass.

Local validation: 43 focused DEV/PROD cleanup, raw-retention and exact-plan tests
passed; 100 migration-scope/warehouse cleanup/PROD dry-run/owner-diagnostic tests
passed. Ruff and mypy (149 source files), repository context and dbt parse passed.
Docker build is blocked because Docker Desktop's Linux engine pipe is absent.
Current hosted quality and independent review remain required. No live SQL was
executed to test V166 and no real deletion or source acquisition occurred.
