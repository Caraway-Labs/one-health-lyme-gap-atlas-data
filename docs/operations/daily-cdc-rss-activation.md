# Daily CDC RSS execution: implementation and activation packet

Status: draft implementation; no deployment, migration, registry write or credential placement executed.

This reuses the existing DigitalOcean application and canonical ingestion runtime for the three accepted CDC sources. The owner approved daily execution on 2026-10-21 at 21:16Z. Existing scientific/source-use decisions are retained; this is an operational cadence activation only.

## Invariants

- Preserve all six existing production jobs, including their exact images, commands, schedules and credentials.
- Add only `intelligence-feed-daily`, daily at 18:15 America/Denver, one instance. Disabled by default in application settings.
- Claim each source/day in the existing ingestion ledger before provider I/O. A SUCCEEDED or RUNNING attempt is not claimed again. A terminal FAILED attempt can be claimed again the same UTC day, up to 3 attempts for that source.
- Preserve one attempt, 30 seconds per HTTP operation, 2 MiB, 250 items, verified TLS, no redirects and existing 30-day raw-copy enforcement.
- Each daily source has its own 900-second owned-work budget (`DAILY_SOURCE_BUDGET_SECONDS`, passed to `PilotBudget`) inside a 960-second process watchdog (`DAILY_SOURCE_WATCHDOG_SECONDS` = budget plus two 30-second grace windows). The five-minute pilot cap still applies to pilot/prerequisite paths. When the budget expires, the budget wrapper blocks the run's own writes, so the runner records the run FAILED on a fresh short connection (`intelligence_daily_deadline`): the RUNNING checkpoint becomes FAILED with category `DEADLINE`, code `PILOT_BUDGET_EXCEEDED`. No claim is left RUNNING by a budget expiry.
- Each daily source runs in its own child process. The 960-second watchdog is armed only in that child. When it fires, the child logs `intelligence_daily_hard_kill` with the allowlisted stage it was in (`ACQUIRE`, `NORMALIZE`, `LOAD`, or another ingestion stage) plus RSS and peak RSS in kibibytes, then marks the run FAILED on a new Snowflake session (`intelligence_daily_hard_kill`, classification `INTELLIGENCE_DAILY_HARD_KILL`, checkpoint code `PROCESS_HARD_KILL`). The redacted error names that stage. The write is bounded by `LEDGER_TIMEOUT_SECONDS` (30s) and a 15-second statement and queue timeout. If the write fails or the bound expires, the child still exits 124. The parent then starts the next source. A hard-killed child does not stop the remaining sources. The log line has no payloads, record contents, SQL text, tokens or connection strings. Pilot and prerequisite watchdogs still exit without this ledger write. If the parent has to stop a child that missed that deadline, it logs `intelligence_daily_source_process_exit` with the source id and exit code and continues with the next source. A kernel kill that never reaches this watchdog, such as an out-of-memory stop, can still leave that one ledger row RUNNING; the existing `recover-intelligence-daily-stuck-run` command remains the manual path for that row.
- Daily output includes redacted per-stage timing (`stage`, `status`, `seconds`, `queries`; stages still open at exit are `UNFINISHED`). No payloads, URLs, credentials or exception text.
- Recovery (`recover-intelligence-daily-stuck-run`) terminalizes a RUNNING daily run even when no checkpoint is RUNNING: only the run row becomes FAILED (`INTELLIGENCE_DAILY_PROCESS_EXIT`); PENDING/COMPLETED stages are untouched. Scope guards (code version, source, config checksum) are unchanged. Ledger rows are never deleted or rewritten otherwise.

## Same-UTC-day re-run of a failed source

A source whose latest attempt for the UTC day is terminal FAILED can be run again that day. RSS and PubMed (Entrez) sources use the same rule. A SUCCEEDED or RUNNING attempt is not run again. A mismatched checksum or `code_version` fails closed. There is no separate per-incident approval. The new ledger row, the GitHub run URL, and an issue comment are the audit trail.

- Hard cap: 3 attempts per source per UTC day. Attempt 4 and higher is refused before SQL (`INTELLIGENCE_DAILY_ATTEMPT_CAP`).
- Manual one-shot workflow input `reopen_attempt` must match `^[1-3]$`. Values 2 and 3 require `source_id` for any registered daily source, including `pubmed-tick-borne` and `pubmed-lyme-borrelia`. The command is `run-intelligence-daily --reopen-attempt N --source <id>`. `claim_daily_run` receives `reopen=True` for that attempt. The manual job does not set a reopen environment variable and does not pass `--scheduled-same-day-retry`. Its spec sets `timeout: 1h35m`, one full pass and no retry, instead of the 30 minute deployment default. One source is the PubMed case. RSS accepts one to five repeatable `--source` values. Sources that are not selected finish as `SKIPPED_NOT_SELECTED` and do not fail the job. An empty `source_id` or the value `all` is rejected before the spec is built. Preflight and recovery modes cannot be combined with a re-run. Recovery passes the same `--source` and refuses a run whose `resource_key` does not match it. The workflow refuses a manual dispatch from 17:00 through 18:15 America/Denver (`INTELLIGENCE_DAILY_MANUAL_WINDOW_CLOSED`), which stays on the local clock across the November change.
- The standing `intelligence-feed-daily` command is `run-intelligence-daily --scheduled-same-day-retry`. That flag is the only path that retries a source the same run marked FAILED, once, as attempt 2, after the other sources finish. The retry phase stops when one RSS parent wait plus one PubMed walk (1020 + 180 seconds) has elapsed; sources not started keep their first FAILED outcome. The same per-source bounds apply (900/960/1020 seconds; PubMed 5 requests and 180 seconds). A retry that is still FAILED stays FAILED. SUCCEEDED and RUNNING sources are not retried. A manual full run does not retry.
- `claim_daily_run(..., reopen=True)` is required before any SQL when the run id is attempt 2 or 3. The process environment is not that gate. A missing `reopen` argument is `INTELLIGENCE_DAILY_REOPEN_REQUIRED`.
- The attempt run id is `uuid5(...:{source}:{day}:attempt-N)`, an additional immutable ledger row. Attempt N is admitted only if attempt N-1 (the base id for N=2) exists for the same source and checksum, with `code_version=intelligence-daily-v1` and terminal `status=FAILED`, read inside the same transaction as the write-guard bump. RUNNING, SUCCEEDED, missing or mismatched priors are denied; an existing attempt-N row returns ALREADY_CLAIMED. Prior rows are only read.
- Never delete or rewrite attempt rows.
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

## DEV bulk LOAD rehearsal (cdc-mmwr, pre-PROD promotion)

After merge of the bulk LOAD recovery (#786), run one bounded DEV proof against real
Snowflake before promoting the immutable image to PROD:

```bash
gh workflow run run-ingestion.yml \
  --repo Caraway-Labs/one-health-lyme-gap-atlas-data \
  --ref main \
  -f source_definition=config/sources/intelligence_cdc_mmwr.yml \
  -f environment_name=dev \
  -f operation=intelligence-cdc-mmwr-rehearsal \
  -f tier=B
```

The job uses `OH_LYME_DEV_PIPELINE_SVC` / `OH_LYME_DEV_RUNTIME`, runs the full
ACQUIRE → NORMALIZE → bulk LOAD → publish path twice, and prints per-pass
`statement_count`, `items_loaded`, insert/replay counts, and whether the second
pass inserted zero new rows. If stage `PUT` or `PARSE_JSON`/`MERGE` fails for
privileges, the log includes the exact Snowflake error and the reviewed grant
hint without attempting a workaround.

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

## Baseline digest alignment before the seventh job

Production Update rejected the preflight job when the reviewed immutable digest was
present on DEV but not yet referenced by any existing production component. The daily
helper now performs a separate Update that pins all six approved jobs to the reviewed
digest first, using the same digest-only promotion pattern as the standard production
promotion path and without adding components. Only after that alignment does it add
the preflight or scheduled daily job.

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

## Production-context validation only

To isolate the local-versus-workflow credential context, the existing protected
production job supports `intelligence_daily_validate_only=true` together with
`intelligence_daily_only=true`. Set `daily_credential_placement_approved=false`;
all other mutation modes must be false. This selects validation, not deployment.
The native production gate, existing credential, permissions and concurrency
group remain unchanged. Review the exact new main commit before dispatch.

The helper accepts only the exact already DEV-verified failed-attempt image
`sha256:3b3002e1fed2386b336fb14951e06e13a0ddecdfbde1d63945fcf0ca91149226`.
It checks the unchanged six-job baseline and actual DEV digest, then makes two
Propose requests: original digest control and verified digest. Both preserve the
actual public sizing, command, schedule, image, feature and empty-ingress fields.
No environment keys/values, encrypted references or private configuration enter
the payload. Unknown or changed public structure fails closed before proposals.

Only acceptance, redacted errors and a normalized-image comparison boolean are
reported. Responses/specifications are not logged or saved. Final readback must
confirm the app specification and active deployment are unchanged. No Update,
deployment, source acquisition, SQL, image push or credential placement occurs.
Passing Propose still does not establish Update-specific source resolution.

## Where to look when a daily run fails

Grafana, not the droplet. The daily job and the manual once-per-day job copy
`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` from a sibling
job that already exports traces. No new secret is required. Logs use the same
headers against `/v1/logs` on that host (derived by replacing `/v1/traces`, or
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` if set). Without those variables the job
still runs and writes JSON lines to stdout.

Import `ops/grafana/intelligence-daily-dashboard.json`. Filter
`service_name=data-job` and `component=intelligence-daily`.

- Tempo: one trace per invocation. Spans are `atlas-data.cli`,
  `intelligence-daily.job`, `intelligence-daily.source`,
  `intelligence-daily.stage` (ACQUIRE, NORMALIZE, LOAD, PUBMED, CLAIM), and a
  span per Snowflake statement and outbound HTTP call. Attributes include
  `source_id`, `run_id`, `attempt`, `stage`, and `step`.
- Loki: the same events as JSON, including `snowflake.statement`,
  `http.client`, `checkpoint.read` / `checkpoint.write`, `ledger.read` /
  `ledger.write`, `lease.acquire` / `lease.renew` / `lease.release`,
  `guard.enter` / `guard.exit`, `stage.heartbeat` every 30 seconds while a
  stage is open, and `source.summary` / `run.summary`.
- A hang is the last `stage.heartbeat` for that source. The dashboard's open
  stage panel is the stage that has had no heartbeat for 120 seconds.
- Statement logs carry a fixed label such as `ledger.guard.update`, duration,
  row count, exception class, errno, and sqlstate. They do not carry SQL
  parameters, row text, or payloads. HTTP logs carry host and path, not the
  query string.
