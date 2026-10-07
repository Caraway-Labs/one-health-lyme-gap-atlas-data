# January 2025 reviewed annual donor handoff

This corrects the DATA #443 diagnostic role/query mismatch without granting the
ingestion runtime access to release base tables. The previous failure established
an object-or-access error, not object absence. Product approval covers January
county weather engineering; it does not establish technical donor provenance.

## Producer and independent review

`climate_membership.export_donor_handoff(cursor, output, code_sha,
expected_account_sha256, expected_region)` is a SELECT-only helper for the existing
protected DEV migration-deployer service identity. It verifies the exact effective
user/role/DEV database/`OH_LYME_DEV_INGEST_XS_WH`, live account-locator hash and region.
It reads the published ATLAS donor and bundle digest with a server-side manifest
size bound, validates all five annual source slots, and compares the donor to
`CURRENT_RELEASE_V` before atomically writing JSON. The artifact omits raw user,
account and warehouse identifiers, and includes a redacted account hash/region
binding. A hash and role string do not authenticate the operator by themselves.

The proposed bounded callable is `climate_donor_diagnostic.producer`; its shell
entrypoint is `scripts/verify_january_donor_dev.py`. It reuses the existing diagnostic
bounded cursor, pricing validation, Standard capability and warehouse observations.
It is **not wired into an authenticated workflow**. No connection, migration, grant,
publication, live artifact or credential configuration occurred while preparing it.
The existing $7 guard blocks it before connection; tests use explicitly artificial
prior reservations to exercise the offline transport and failure boundaries.

### Exact proposed invocation, not an available dispatch route

After independent review, specific authorization for the authenticated route and
artifact retention, and approval of a finite revised cost cap, the proposed placement
is an exclusive read-only branch of the existing protected DEV `deploy-dev.yml`
diagnostic step, **before** its separate `snow sql` identity query and every migration
command. Reuse that step's existing ephemeral key handling and DEV service credentials;
never copy credentials to another environment or invoke the publish workflow.
No workflow enablement or upload route is added by this PR.

The complete bounded call in that already-authorized protected runner would be:

```bash
# FUTURE PROPOSAL ONLY: these placeholders are not approved execution inputs.
# Existing protected DEV environment supplies service settings and ephemeral key.
test "$(git rev-parse HEAD)" = "$REVIEWED_PRODUCER_SHA"
test "$GITHUB_SHA" = "$REVIEWED_PRODUCER_SHA"
export JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX="$(date +%s)"
# JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE: freshly reviewed redacted owner Standard
# account-hash/region evidence and official public price ceiling; never secrets.
uv run python scripts/verify_january_donor_dev.py
```

The proposed route must reject simultaneous diagnostics, publication and migrations;
verify an exact reviewed main SHA; retain its existing five-minute execution-step
limit; and retain the local safe donor/closed receipt through a specifically approved
private artifact destination with 14-day retention. The receipt and artifact contain
no raw account locator or connection secrets. The operator's actual identity and
run provenance still need independent verification. The normal publish workflow
can apply migrations and publish, and is prohibited for this read.

### Enforced bounds in the offline callable

- One connection; exact configured migration user/role/DEV database before login.
  Select the exact existing ingest XS warehouse in this session, without altering
  its configuration or adding a grant. Missing usage or visibility stops the read;
  it never falls back to a different warehouse or identity.
- Connection-inclusive 15-second execution watchdog on Linux, armed before connect.
  Login/network/socket limits are five seconds; server statement limit five seconds,
  queue limit two seconds, detached-query abort enabled. Missing enforcement stops
  before connection. Early step clock preserves 60 seconds for receipt/retention.
- Maximum six application SELECT/SHOW statements; normal success uses five:
  account/identity binding, exact warehouse SHOW, helper identity recheck, published
  donor read, and current-view comparison. No usage/history read or cancellation
  SQL is added. Remote result batches stop before chunk download.
- Connector retry attempts are zero; its backoff stops rather than incrementing a
  retry. No reconnect, alternate identity or role-switch path exists.
- SDK statement timeout cancels the active request. The overall watchdog requests
  the pinned SDK's active-query SIGINT cancellation where a statement is active;
  the receipt records a request, not assumed cancellation success. Fifteen seconds
  bound cancel/cleanup, with a 30-second total ceiling; close uses `retry=False`.
  Server timeout and detached abort remain required safeguards, not proof of billing.
- Stage output under a temporary name. Failed identity/account/cost/manifest/pointer,
  transport, watchdog or cleanup preserves an existing reviewed donor and removes
  pending output. Install the donor only after successful bounded connection close.

Retain the actual protected receipt and independently review identity checks, reviewed
code SHA, account/region binding, artifact digest and full manifest. Never manufacture
an artifact from a fixture or infer it from a failed query. Commit the actual reviewed
safe JSON under `docs/contracts/climate/reviewed-donors/` through a reviewed PR; no
live artifact is included here. Raw private operational evidence belongs outside Git.

## Runtime consumption

The existing frozen-membership operation accepts `january_donor_handoff_path` and
`january_donor_handoff_sha256`. Independent review must bind both inputs to the actual
protected producer run and reviewed producer commit. The permitted directory is
anchored lexically beneath the canonical checkout; it is never resolved outward to
redefine the boundary. Resolve the candidate once and require that exact path to
remain inside this boundary before reading it. Allowed-directory, ancestor, nested
and file symlink escapes all stop before file consumption or connection.

Missing inputs, files over 64 KiB, digest mismatch, unknown fields, invalid/future
timestamps and invalid annual manifests fail before connection. File reads are bounded
at 64 KiB plus one byte, including growth after the initial size observation.

The consumer compares its actual account-locator hash and region to the reviewed
donor, with the same freshly verified owner capability binding. The runtime reads
only the intended current-release view for donor verification. Release ID and bundle
hash must equal the artifact both before and after ordered capture export. Missing,
duplicate, changed or inaccessible view rows block export. Full manifest validation,
selected-run/input hashes, row-count checks, capture digest and atomic replacement
remain required. The artifact is a read-only candidate, not approval, publication,
DEV acceptance or API acceptance.

## Conditional cost proposal, not approved

Preserve the full consumed forecast reservation of **$6.836666666666667** against
the approved **$7 total cap**. Actual invoiced charges remain unknown. The remaining
$0.163333333333333 does not authorize either producer or consumer. Both checked-in
guards reject another paid attempt before connection; no runtime input raises the cap.

Only if both sessions use the exact observed Standard single-cluster XS warehouse,
verified AWS region/account binding and a fresh official public ceiling of $6/credit,
the proposed single-producer/single-consumer reservation is:

- `5.75` credits/hour = conservative `1.35` maximum Gen2 XS compute plus `4.4`
  cloud-services allowance, without assuming the daily adjustment.
- `1.35/30` credits = **two one-minute warehouse idle tails**, not cloud services.
  Retain this allowance separately for each session, even on the same warehouse.
- Producer: 15 seconds including connection plus 15 seconds cancel/cleanup; reserve
  60 seconds for resume/minimum billing and conservatively for cloud services:
  `(60 * 5.75 / 3600 + 1.35 / 30) * 6 = $0.845`.
- Consumer: 50 seconds including connection plus 15 seconds cleanup:
  `(65 * 5.75 / 3600 + 1.35 / 30) * 6 = $0.892916666666667`.
- Shared uncertainty reserve: $1. Additional reservation: **$2.737916666666667**.
- Prior plus proposal: **$9.574583333333334**. A conditional **$10 total cap**
  covers this pair under these assumptions; it is not authorization or invoice proof.

Do not execute until Matthew approves the finite revised cap and authenticated
producer/artifact route, and independent review accepts the exact invocation and
both actual warehouse/capability bounds. Any cap change must be a separate reviewed
change based on the actual approval, with no automatic retry or released reservations.
The producer can fail before donor proof, and inline-only 50-second consumption may
still be insufficient for complete membership; a blocked receipt requires stopping,
not a retry or a claim of acceptance. Fresh owner evidence expires after 24 hours;
do not refresh its original verification timestamp merely to make a run possible.

No grant, credential setting, warehouse configuration, PROD publication or historical
expansion is authorized by this correction. Live DEV donor/membership proof, modeling,
governed publication and dependent API acceptance remain separate downstream gates.
