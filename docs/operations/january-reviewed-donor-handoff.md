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

The bounded callable is `climate_donor_diagnostic.producer`; its shell
entrypoint is `scripts/verify_january_donor_dev.py`. It reuses the existing diagnostic
bounded cursor, pricing validation, Standard capability and warehouse observations.
It is wired to the existing protected DEV `deploy-dev.yml` job only through the
exclusive `diagnose_january_pair` read-only mode. No migration, grant or
publication is part of that mode.
The owner-approved $10 total guard is now checked in; tests use artificial
prior reservations to exercise the offline transport and failure boundaries.

### Same-job protected DEV invocation

The branch runs before its separate `snow sql` identity query and every migration
command. The protected DEV environment already holds both established service
identities. The donor child process receives the migration-deployer credential;
after that key file is removed, the membership child process receives the runtime
credential. Each callable verifies its configured and effective identity, account,
region and warehouse. Neither switches roles or copies credentials to another
environment.

The workflow requires exact reviewed green `main`, `expected_pending_json=[]`,
all other diagnostic modes off, and the existing redacted budget evidence. It
sets one clock just before the pair. The sequence is:

```bash
# In one protected job, with separate child-process credentials:
uv run python scripts/verify_january_donor_dev.py
# Check the donor receipt digest against the actual private file, then run:
uv run atlas-data source nclimgrid-pilot-measure --action frozen-membership \
  --run-id c2eb2146-005d-44d2-bac4-e2805ca42577
```

The job creates a mode-0700 directory inside the ephemeral checkout's permitted
`reviewed-donors` path. It verifies the donor receipt and SHA-256 before the
runtime consumer starts, then verifies the consumer receipt, exact donor digest
and 389,856 rows, including the actual membership file digest. Only bounded
summary evidence goes to logs; the donor and capture-ID artifact are never
printed or uploaded. Their complete contents remain recoverable from the
existing published release manifest and retained V103 revision rows, bound by
the logged release/bundle, manifest digest, selected run, row count and tuple
digest. The EXIT trap deletes all job-local files. The normal publish workflow
is prohibited for this read.

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

Retain the protected run's compact receipt evidence and independently review
identity checks, reviewed code SHA, account/region binding, artifact digest,
warehouse cost observations and full manifest. Re-read the complete manifest
from the existing `PRESENTATION.SEMANTIC_RELEASES` row by release ID and bundle
hash, then compare its canonical digest with the run proof. The full membership
list is reconstructed from retained V103 rows and compared with the frozen
five-field digest before building the governed extension. Never manufacture an
artifact from a fixture or infer it from a failed query. Raw private operational
evidence and capture IDs do not belong in public Git artifacts.

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
donor, with the same account-bound owner capability evidence. The runtime reads
only the intended current-release view for donor verification. Release ID and bundle
hash must equal the artifact both before and after ordered capture export. Missing,
duplicate, changed or inaccessible view rows block export. Full manifest validation,
selected-run/input hashes, row-count checks, capture digest and atomic replacement
remain required. The artifact is a read-only candidate, not approval, publication,
DEV acceptance or API acceptance.

## Owner-approved January diagnostic execution ceiling

On 2026-10-08, the owner approved a **$10 total January climate diagnostic forecast
ceiling** for one bounded donor producer and one bounded membership consumer
attempt. Preserve the full prior forecast reservation of **$6.836666666666667**;
actual invoiced charges remain unknown. The checked-in guards reserve both new
sessions and the shared uncertainty amount before connection. No runtime input
raises the ceiling, and a failed attempt does not release its reservation or
authorize an automatic retry.

On 2026-10-09, after that pair's donor succeeded and its consumer stopped before
querying Snowflake, the owner approved **one additional bounded donor-plus-consumer
execution** and a revised **$15 cumulative January diagnostic forecast ceiling**.
The original prior reservation plus the first pair is **$9.574583333333334** and
remains fully reserved. The new pair reserves up to **$2.737916666666667** at the
same $6/credit public price ceiling, yielding a cumulative **$12.3125** forecast.
The 50-second consumer limit, statement limits, single-attempt policy, and other
cost guards remain unchanged. This approval does not include further retries.

Only if both sessions use the exact observed Standard single-cluster XS warehouse,
verified AWS region/account binding and a fresh official public ceiling of $6/credit,
the per-pair reservation is:

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
- Original prior plus first pair: **$9.574583333333334** under the stated
  $6/credit ceiling. That first attempt is historical; the current cumulative
  reservation and **$15 cap** are stated above. These are forecast guards,
  not invoice proof.

The owner also authorized the reviewed protected DEV diagnostic route using
existing service credentials and private donor artifact/receipt retention up to
14 days. The same-job destination is the private, mode-0700 checkout directory
used only by the protected DEV job, with deletion at job exit; no persistent
storage or public repository Actions artifact is required. Independent review must accept
the exact invocation and actual warehouse/capability bounds. The owner-provided
Standard account capability evidence must match the live account and
cost-relevant warehouse capabilities at execution. Its original verification
timestamp remains unchanged; elapsed time alone does not reject it. No
automatic retry or released reservation is authorized.

### Unused persistent storage candidate

The following Spaces candidate was investigated before the same-job route was
established. It is not a prerequisite or dispatch path for the January pair.

The existing `one-health-lyme-gap-atlas-data-dev` Space was investigated as a
possible separate-job transport. Its scoped runtime credential could not read
bucket ACL metadata. No Spaces upload, download, permission change or retention
configuration is part of the same-job route.
The producer can fail before donor proof, and inline-only 50-second consumption may
still be insufficient for complete membership; a blocked receipt requires stopping,
not a retry or a claim of acceptance. Do not refresh the owner evidence's
original verification timestamp merely to make a run possible; a material
account or entitlement change requires review.

No grant, credential setting, warehouse configuration, PROD publication or historical
expansion is authorized by this correction. Live DEV donor/membership proof, modeling,
governed publication and dependent API acceptance remain separate downstream gates.
