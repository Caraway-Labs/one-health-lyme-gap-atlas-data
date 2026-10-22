# Daily CDC RSS execution: implementation and activation packet

Status: draft implementation; no deployment, migration, registry write or credential placement executed.

This reuses the existing DigitalOcean application and canonical ingestion runtime for the three accepted CDC sources. The owner approved daily execution on 2026-10-21 at 21:16Z. Existing scientific/source-use decisions are retained; this is an operational cadence activation only.

## Invariants

- Preserve all six existing production jobs, including their exact images, commands, schedules and credentials.
- Add only `intelligence-feed-daily`, daily at 07:00 America/Denver, one instance. Disabled by default in application settings.
- Claim each source/day in the existing ingestion ledger before provider I/O. Duplicate invocations, including after a failed attempt, cannot retry that source that day.
- Preserve one attempt, 30 seconds, 2 MiB, 250 items, verified TLS, no redirects and existing 30-day raw-copy enforcement.
- Immutable source v2 packages activate only the existing three approved sources. Manual/paused states suppress daily execution. No new scientific approval is asserted.
- V164 preserves existing published v1 entries only across the exact pinned approved active v2 transition; future, revoked or unknown transitions fail closed. Cross-version duplicate entries are collapsed.

## Required rollout order (NOT executed)

1. Complete independent review and focused/full hosted CI, then verify exact merged-main and immutable DEV-tested image.
2. Finish the already dispatched Outbreaks v1 acceptance run before any v2 registration; do not duplicate it.
3. Execute V164 through the existing protected migration-only path after applicable approval. Verify ledger checksum and unchanged production applications.
4. Register each exact v2 source using the existing protected registration workflow, with native human production approvals and empty pending migrations.
5. Resolve the identity/credential-placement prerequisite below before any application update.
6. Deploy only the explicitly approved temporary preflight component. It performs runtime identity and source-readiness checks, without provider acquisition. Creating this component IS a production application mutation and a new credential recipient.
7. Verify successful exact-image preflight and actual runtime identity. Replace only that component with the scheduled daily job through the protected daily-only path; preserve the original six jobs exactly.
8. Verify actual scheduled execution, per-source ledger/provenance, API pagination/counts, and retention metadata. Do not claim recurring operation from configuration alone.

## Security prerequisite: currently blocked

The encrypted existing component configuration does not prove the actual Snowflake service username. No actual scheduled identity authentication proof has been obtained. No deployment is authorized merely by observing encrypted credential references.

Before any deployment, require either actual existing service identity proof or explicit owner approval for the following new credential placement. The workflow and deployment helper fail closed without the separate placement flag; an agent must not infer approval or submit native human approvals.

Source component: `approved-source-ingestion`, app `5d8966ed-d152-4a78-bdd6-14553dbc1483`.
New recipients: temporary `intelligence-feed-preflight`, then permanent `intelligence-feed-daily`. The temporary name fits DigitalOcean's 32-character component-name limit; the originally proposed `intelligence-feed-daily-preflight` was rejected before any application change in run 39697461617. This shortens the same approved temporary recipient's name without changing its credential scope, command or purpose.
Existing credential key names copied in memory only: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_B64`, `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`, `SPACES_ACCESS_KEY_ID`, `SPACES_SECRET_ACCESS_KEY`. Existing non-secret connection/storage scope is copied with them. No keys are minted, logged, written to disk or granted new database privileges.
Expected role/database/warehouse: `OH_LYME_PROD_RUNTIME` / `ONE_HEALTH_LYME_GAP_ATLAS_PROD` / `OH_LYME_PROD_INGEST_XS_WH`; canonical runtime verifies the intended service user as well. Failure must prevent scheduled activation.

## Validation status

Draft. Focused tests, type checks, full hosted CI and independent technical review remain in progress. No production readiness or activation claim is made by this document.

# Safe rejected-update diagnostics

A nonzero `doctl apps update` result still raises immediately without retry or
activation. Each output channel is decoded once. Actual error prose is retained
after in-memory redaction of known secret values, JSON/URL/base64 representations,
and token, authorization-header, credential-assignment and private-key patterns.
Unknown validation words are not replaced with a vocabulary marker. The existing
four-category summary remains supplementary; it never filters the prose.

Every unrecognized app/component environment key is private regardless of its
declared type. Only a fixed list of documented public connection/control keys is
exempt, and an explicit SECRET type overrides that exemption. The active
DigitalOcean token is also redacted. Percent-hex matching tolerates mixed casing
and nested escapes without case-folding literal secret bytes. Embedded structured
payloads are withheld wherever they appear after envelope removal; known-value
redaction happens before cutting a payload, so partial secrets cannot escape. Raw output, traces and specs must never be emitted or retained.
Structured payloads, malformed JSON and oversized input channels are withheld.
Redaction precedes truncation: at most eight messages, 2,048 characters per message
and 8,192 total, with an explicit truncation indicator. These bounds and redaction
can still make an error incomplete; a summary is not automatically a root cause.

Fixtures use synthetic loopback errors and credentials with the pinned doctl
1.160.1 JSON stdout shape. The representative image-validation prose is not a
claim about the unknown historical HTTP 400. Preparing this diagnostic change
performs no provider update and authorizes no production attempt.

## Explicit immutable image source refresh

Run 39726707822 rejected the preflight update with HTTP 400 and request ID
`def74747-9fa3-442e-9292-c30a2a34cb6a`. The retained error reports that the
repository is known but the requested image version is not configured for this
app. The requested digest existed in DOCR and had passed actual DEV execution;
production remained on its original six jobs, with no preflight installed.

The pinned [doctl 1.160.1 implementation](https://github.com/digitalocean/doctl/blob/v1.160.1/commands/apps.go)
maps `--update-sources` to `AppUpdateRequest.UpdateAllSourceVersions`; the default
is false. The daily helper now explicitly requests source refresh to resolve the
new immutable image version. An offline pinned-CLI loopback comparison confirms
that this changes only that request boolean and leaves the submitted spec intact.
This is an evidence-backed repair, not proof of production acceptance.

Because the option applies to all sources, rendering fails closed unless every
existing job has only the expected DOCR registry/repository and a SHA256 digest.
Tags, deploy-on-push settings, Git-backed jobs, and other component classes are
rejected before any update. Each existing job is copied unchanged, including its
digest, command, schedule and environment. No new credential, permission or source
scope is introduced. Both phases retain the existing single-attempt, no-retry
behavior and native protected production approval.
