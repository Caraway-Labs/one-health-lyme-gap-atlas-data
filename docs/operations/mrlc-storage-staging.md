# Reviewed 2025 MRLC package staging

The user explicitly approved the separately public official MRLC HTTPS ZIP route
on 2026-10-04 after the exact-version USGS S3 path returned 403. This route never
calls USGS S3, changes identity/grants, or represents ZIPs as S3-versioned tiles.
Scope is only 2025 CONUS Land Cover, Fractional Impervious Surface and Land Cover
Change, to the existing private DEV Spaces bucket. Snowflake remains plan only.

Fresh anonymous metadata verified three 200 HEAD responses and three conditional
64 KiB central-directory range reads on 2026-10-04. The pinned manifest records
exact HTTPS URLs, strong HTTP ETags, Last-Modified, lengths and every ZIP member's
name, compressed/expanded size, CRC, compression method, flags and attributes.
Canonical manifest SHA-256:
`efc10176621a16b8d28bf714cb667d72b467cbfae1434c79243ef1558993db5a`.
Original packages total 4,269,391,159 bytes; their nine TIFF/XML/auxiliary XML
members expand to 4,335,547,988 bytes. XML and sidecars are already inside ZIPs.
No byte equivalence to S3 or publisher cryptographic checksum is claimed.
Official distribution: https://www.mrlc.gov/data/project/annual-nlcd .

## Capture and integrity

The helper reuses reviewed streaming hash, request/time budget, fixed DEV
settings and source-independent client guards. It is a storage-only acquisition
handoff, not a new ingestion/checkpoint framework or governed capture ledger.
Use `python -m lyme_gap_atlas_data.mrlc_storage_staging --execute --capture-only
--manifest config/annual-nlcd-2025-mrlc-staging-manifest.json --directory <private-folder>`.
No AWS profile is used. HTTP redirects, implicit netrc/proxy credentials and
automatic retries are disabled; connect/read timeouts are 5/30 seconds.

An exclusive owned lock precedes file/receipt access and requests. Every existing
package SHA and expanded-member SHA/CRC receipt is checked, and all three current
HTTP HEAD identities must match before any full GET. GET uses both If-Match and
If-Unmodified-Since and validates response metadata/encoding. Sequential 8 MiB
streams have exact length caps. Each ZIP is hashed in full, its complete directory
must match the frozen inventory, and every member is read in bounded chunks to
verify CRC, expanded length and full SHA-256. No file is extracted. Atomic capture
receipts retain original package/member identities, hashes, UTC retrieval times
and executing module hash. Original completed packages are never overwritten;
stale/concurrent locks block. Interrupted unreceipted `.part` files are not usable
inputs. Before another paid attempt, reconcile prior exposure and remaining cap.

## Credential-preserving upload

Relay only the three packages, capture receipt, and reviewed code using existing
strict-host-key SSH/SCP to a new owned mode-700 UUID folder on worker 597363967.
Do not transfer .env, credentials, keys or AWS configuration. Review/merge plus
exact-head and merged-main green CI are prerequisites. Recheck live disk and the
loaded/inactive PMC service; never change or stop that service. The previously
reviewed five-request Spaces canary verified conditional creation and full hash
readback; retain its tiny objects. This change makes no provider capability claim
beyond that recorded evidence.

`scripts/run_nlcd_storage_once.sh <owned-relay-folder> mrlc-stage` uses the existing
pinned image/env-file in place, read-only reviewed source bind, no exposed ports,
0.5 CPU, 512 MiB RAM, 64 PIDs, 1800-second external deadline and ownership-labelled
exact-container cleanup. CLI also has a hard 1800-second process watchdog and
between-chunk checks; 34 request maximum, source 4,269,391,159 bytes, destination
readback at most that plus 65,536 bytes. The script is forced to LF by the narrow
`.gitattributes` entry to prevent the previously observed CRLF launch failure.

Upload performs complete capture/member verification before destination requests.
All three destination HEADs pass before PUT. A persistent UUID namespace under
`dev/source-staging/annual-nlcd-mrlc-c1v2/2025/<manifest>/<uuid>/` and exclusive
session lock isolate writes. Existing mismatches stop; compatible objects need
full SHA readback on resume. Local packages are streamed directly from disk, with
no second spool/extraction copy. Every package requires full destination SHA
readback. Only then is the immutable distribution manifest uploaded and itself
readback-verified. It includes member/package identities, hashes, capture times,
executing code hash and destination keys. A source revision/archive hash and
actual attempt times/requests/bytes are additionally retained by the operator.

Packages plus 256 MB reserve need 4,525,391,159 bytes on the existing worker.
Previously measured free space was 8.36 GB; recheck before relay. Laptop also needs
the complete package bytes plus reserve. Decoded national arrays are not loaded.

## Shared $10 ceiling and remaining work

No new infrastructure/subscription is created. Public HTTPS source does not incur
AWS requester-pays charges. The conservative combined relay/upload/readback
transfer/request envelope is $0.20/GiB plus $0.01 = approximately $0.80524; ancillary
reserve $9 gives a forecast below $9.806. Reserve includes prior metadata/canary,
preparation/CI, existing worker usage and retained storage; it is not a measured
invoice or account billing reservation. Existing fixed-size worker adds no new
compute subscription. At current excess storage pricing $0.02/GiB-month, seven
years of package retention entirely above included storage is about $6.68; future
prices/retention changes are not prepaid guarantees. Sources:
https://docs.digitalocean.com/products/spaces/details/pricing/ . Prior S3 attempt
made no body GET; metadata exposure was 7 preparation calls, at most one failed
HEAD and one diagnostic HEAD; Spaces canary five calls; offline audit zero calls.
All attempts share $10, with no automatic paid retry. Actual charges remain
unmeasured; report forecast versus actual separately.

Staging does not admit mosaics to #196, publish measures or write Snowflake.
Subsequent processing must retain the seven frozen measures and #424 TIGER
geometry, use bounded raster windows, coverage/valid-area states and resumable
county partitions. Keep original ZIPs and hashes immutable; any extracted input
must match recorded member hashes. Persist only seven aggregate rows/county-year
through existing compressed JSONL and internal Snowflake bulk stage, with short
set-oriented transactions, validation/revision lineage and fixed warehouse/time/
credit limits reviewed before execution. No direct Spaces external-stage
compatibility is assumed. Processing and database execution remain held.

## ZIP parser resource preflight

Before constructing `ZipFile`, the same open file handle undergoes bounded EOCD,
ZIP64 locator/record and central-directory validation. Tail reads are at most
65,557 bytes, ZIP64 records exactly 56 bytes, directory at most 65,536 bytes,
member count at most 16 and exactly the frozen inventory count (three/package).
Directory offsets, entry extents, actual count, disk numbers, EOCD comments and
file length must agree. The parser accepts ordinary single-disk classic ZIP and
fixed ZIP64 EOCD even at small file sizes; extensible records, concatenated
archives, directory signatures and trailing data are outside this contract.
Sparse 1 GiB directory declarations reject before either a large read or stdlib
parser construction. No national package is needed to run this regression.

The shared-cap execution prerequisite is the explicit
[cost reconciliation](mrlc-staging-cost-reconciliation.md). Confirm its known
exposure, live runtime and retention/rate assumptions before any execution.

No package body capture, relay or upload has occurred in this PR.
