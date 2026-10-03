# 2025 Annual NLCD storage-only staging

This additive helper supports the user-approved 2025 CONUS acquisition/staging
within a $10 total ceiling. It does not register sources, write Snowflake, admit
mosaics to #196's tile contract or publish measures. Exact six S3 TIFF/XML keys,
versions and bytes are frozen in `config/annual-nlcd-2025-staging-manifest.json`;
canonical SHA-256 is pinned in code. Source bytes total 4,335,339,528.

The destination is only the already approved private DEV Spaces endpoint/bucket.
Keys live under `dev/source-staging/annual-nlcd-c1v2/2025/<manifest-digest>/<private-session-uuid>/`.
Before any body download, every source version/size/ETag and destination key is
HEAD-checked. Reuse requires matching stored identity and full streaming SHA-256
readback. A mismatched existing object blocks; it is never overwritten. Missing
objects are created only in a fresh collision-resistant private session namespace,
protected by an exclusive local lock. Retries retain session state and reuse exact
keys. Provider conditional PUT support is not assumed; no claim of a distributed
conditional-create guarantee is made. Independent sessions use separate keys.

One object at a time is spooled to temporary disk (at most 1,863,988,327 bytes
plus a 256 MB free-space reserve), in 8 MiB chunks, then uploaded and read back.
No multipart API is used, so there are no owned partial multipart uploads to
abort. Failure leaves any complete objects available for verified restart; no
objects are deleted. Successful receipts include source identities, full hashes,
byte counts and destination keys; the immutable manifest is itself uploaded and
readback-verified only after all six members. Local receipt is an acquisition
handoff, not a Snowflake governed-capture ledger entry.

SDK clients disable retries and bound connect/read timeouts (5/30 seconds).
The helper allows 34 SDK calls, one complete source-body pass, one destination
readback pass plus a 64 KiB manifest allowance, and checks a 30-minute elapsed
ceiling between calls/chunks. CLI adds a 30-minute hard process watchdog, and the worker wrapper imposes an
external container deadline/cleanup too. A blocked upload cannot be bounded
merely by checking a Python clock between calls. Do not launch outside these
reviewed deadline guards. There is no unattended retry. Before any restart, reconcile the
prior request/byte exposure and remaining approved budget; the CLI is not an
account-level billing reservation.

The forecast uses a conservative combined marginal transfer allowance of
$0.20/GiB plus $0.01 for bounded requests, above observed AWS/Spaces rates.
The caller must substantiate an additional runtime/storage/non-transfer cost
bound (0–$9) from the existing execution environment. Combined forecast must be
at most $10. This is an exposure check, not a measured invoice or authority to
invent a runtime price. Retention/allowances and already incurred preparation
charges must be included by the execution owner. Source and destination read
bytes are reported separately; existing artifacts still require verification.

Run only after independent review/merge/green main and verified existing AWS
and Spaces identities in the same approved execution environment. Use normal
AWS profile/SDK authentication and existing protected Spaces settings; never
copy credentials or create new persistent keys/grants. CLI:

```
python -m lyme_gap_atlas_data.nlcd_storage_staging --execute \
  --manifest config/annual-nlcd-2025-staging-manifest.json \
  --scratch <approved-private-scratch> \
  --non-transfer-cost-bound-usd <verified-bound>
```

## Credential-preserving relay

The capture host uses its existing AWS profile, never Spaces credentials. Create
an owned private capture folder, impose a hard process deadline, then use the
same CLI with `--capture-only`. Successful members are written atomically with
source version/ETag/size/full-hash receipts; interrupted members remain `.part`.
Existing complete files require matching receipts and digest before reuse.

Transfer only these six fixed files, `capture-receipt.json`, and reviewed code
using existing authenticated SSH/SCP with `StrictHostKeyChecking=yes`,
`BatchMode=yes`, no automatic host acceptance and no new keys. Never relay an
AWS profile, runtime env file, `.env`, private key or other credentials. Use a
new UUID-named folder under `/var/tmp/atlas-nlcd-relay/`, owner-only mode 700;
keep its session state on retry. Verify receipt and each file hash before upload.

Upload mode `--relay-directory` uses a verified directory reader, not an AWS
client. Each file is checked against its original captured member/digest before
Spaces writes, with another digest check after spooling. The existing DEV
runtime consumes its own settings in place. It never exports them or connects
to Snowflake. Direct S3 raster assets are 4.335 GB, not ZIP+extracted copies.
Relay assets + largest temporary spool + 256 MB reserve need about 6.46 GB;
live free-space checks still apply. Observed worker free space was 8.36 GB.

`scripts/run_nlcd_storage_once.sh` enforces a 120-second canary or 1800-second
upload deadline and exact ownership-labelled container cleanup. It uses the
existing pinned runtime image and env-file in place, read-only reviewed code,
0.5 CPU/512 MiB/64-PID limits and no exposed ports. It refuses when the PMC
service is active; never stop or modify that service to proceed. The $9 ancillary
reserve covers a conservative seven-year storage illustration at current rates
plus preparation/canary/CI overhead; prior-attempt exposure must still be
reconciled before execution. Official Spaces pricing is $0.02/GiB-month beyond
250 GiB included, with $0.01/GiB excess outbound bandwidth. At 4.0376 GiB, even
all seven years beyond the allowance is about $6.78 at unchanged current rates.
The combined transfer/request bound is about $0.818, yielding a $9.818 forecast
bound. Worker is an existing fixed-size s-1vcpu-1gb instance, image already
cached; no new compute resource is created. Future rate changes are not a
measured bill or guaranteed prepaid price. Sources:
https://docs.digitalocean.com/products/spaces/details/pricing/ and the retained
AWS Oregon regional public price lists. Incoming Spaces bandwidth is free;
Droplet outbound has a separate allowance, so the conservative transfer reserve
also covers relay upload exposure rather than assuming every route is free.

The independent provider canary (`spaces_conditional_canary`) makes at most five
requests against a new unpredictable `dev/staging-canary/<uuid>/` prefix. It
creates a tiny nonsecret private object, attempts conditional creation with
different content, reads back and retains the result plus a tiny receipt. It
never touches existing/source keys or deletes objects. It verifies both response
and original bytes; an ignored header is NOT_VERIFIED. Review this canary before
execution; its outcome is not claimed in this PR. Source-body transfer waits
for that reviewed provider check and the reviewed relay/deadline/cost guards.

No live capture, relay, canary or staging occurred in this change. #594 owns
handoff and separate distribution/processing review; Snowflake remains held.
