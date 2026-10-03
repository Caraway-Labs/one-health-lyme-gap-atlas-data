# 2025 Annual NLCD storage-only staging

This additive helper supports the user-approved 2025 CONUS acquisition/staging
within a $10 total ceiling. It does not register sources, write Snowflake, admit
mosaics to #196's tile contract or publish measures. Exact six S3 TIFF/XML keys,
versions and bytes are frozen in `config/annual-nlcd-2025-staging-manifest.json`;
canonical SHA-256 is pinned in code. Source bytes total 4,335,339,528.

The destination is only the already approved private DEV Spaces endpoint/bucket.
Keys live under `dev/source-staging/annual-nlcd-c1v2/2025/<manifest-digest>/`.
Before any body download, every source version/size/ETag and destination key is
HEAD-checked. Reuse requires matching stored identity and full streaming SHA-256
readback. A mismatched existing object blocks; it is never overwritten. Missing
objects are conditional-created (`IfNoneMatch=*`, private ACL); unsupported
provider conditional creation blocks rather than falling back to overwrite.

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
ceiling between calls/chunks. The execution owner must impose an external hard
process/job deadline too, since a network upload cannot be cancelled merely by
checking a Python clock between calls. Do not launch without that enforced
process limit. There is no unattended retry. Before any restart, reconcile the
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

Current inspected surfaces: laptop has existing AWS profile `nlcd-requester`;
protected generic workflow has Spaces identity, but no inspected existing AWS
identity. This is a concrete execution-location prerequisite, not permission to
copy keys. No live staging occurred in this change. #594 owns the handoff and
separate reviewed distribution/processing work; Snowflake remains held.
