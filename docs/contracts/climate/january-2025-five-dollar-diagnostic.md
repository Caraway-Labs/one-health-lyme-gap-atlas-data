# Approved read-only January diagnostic

Matthew directly approved up to US$5 on October 6, 2026 at 05:04 UTC, separately
from feed/NLCD. Publication and historical execution budgets remain unapproved.
No warehouse write, grant, source download, credential configuration or backfill.

Use the existing protected frozen-membership action on reviewed green main.
Identity is verified inside its one connection; only this exact operation skips
the workflow's separate identity session. Other operations retain it. Maximum
forty SELECT/SHOW statements, fifteen-second statement/socket limits, five-second
queue limit, no request/authentication retry and no role fallback.

The first workflow step records the job's UNIX start time before checkout or
installation. The diagnostic derives its remaining monotonic/POSIX deadline
from the overall five-minute job window, reserving sixty seconds for cleanup
and receipt upload. Fewer than thirty available execution seconds stops before
connection but writes a receipt. Budget-derived shortening can reduce it further.

The pricing input is **public and log-visible**, not transient or digest-only:
Actions can print step environment values. Accept only official HTTPS Snowflake
pricing references, a reviewed public USD/credit forecast, matching CURRENT_REGION,
reviewer identifier and UTC verification time within seven days. No private
invoice/account details, credentials, signed URLs, query strings or fragments.
The receipt labels this OFFICIAL_PUBLIC_PRICE_FORECAST_NOT_ACCOUNT_INVOICE;
actual account-specific billed price/charges remain unknown. Its stored digest
does not imply the raw workflow input was confidential.

Applicable consumption comes from the [Snowflake Service Consumption Table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf),
effective October 2, 2026: Standard Gen1 XS 1 credit/hour; Gen2 XS AWS/GCP 1.35,
Azure 1.25; cloud services 4.4 credits/hour without assuming daily exemptions.
SHOW WAREHOUSES must verify Standard XS, generation 1 or 2, one maximum cluster,
auto-suspend at most sixty seconds and no query acceleration. CURRENT_REGION
binds the quote to its actual cloud/region. No warehouse or monitor alteration.

At the public AWS Oregon US$6/credit forecast, five execution minutes plus a
one-minute suspension tail is 0.135 warehouse credits and at most 0.3667 modeled
cloud-services credits: about US$3.01 plus US$1 noncompute reserve, about US$4.01.
The actual job deadline reduces runtime further. The code conservatively uses
the maximum 1.35 warehouse rate when calculating its deadline. Higher price
forecasts shorten runtime to preserve the US$5 modeled total, never increase
the approved budget. This is a forecast bound, not a hard invoice claim or an
attribution of unrelated shared-warehouse activity.

Require 1 GiB free temporary disk; new warehouse storage is zero. Local retained
IDs/donor output is capped at 32 MiB and fourteen days. Oversized output never
replaces an earlier artifact. No NOAA/TIGER bytes are acquired.

The pinned connector initializes query-request retry context and result-batch
download backoff differently. This diagnostic checks public ResultBatch metadata
before fetch and **refuses remote result chunks**. No chunk GET or retry can
start. Large membership therefore remains unresolved if remote chunks are needed;
the finite stage/remote-batch blocker is useful diagnostic evidence, not a full
export or publication receipt. It does not alter the release contract. A future
full export needs independently reviewed transport policy under its own bounds.

Receipt: actual failing stage, safe query ID if known, effective role, counts,
elapsed time, verified assumptions and safe hashes; no raw SDK messages/endpoints.
A failed execute uses error.sfqid or a changed cursor.sfqid; an unchanged previous
ID is null rather than attributed to the failure. Error 2003 remains
OBJECT_OR_ACCESS_UNAVAILABLE, never proof of absence or missing grants.

One optional same-session bounded query-history read records genuine execution,
bytes and cloud-services usage if available. It is not an invoice; actual billed
dollars remain null until genuine billing evidence is available. Principal and
query IDs remain in the internal receipt, not stdout. A BLOCKED receipt must be
reported separately from workflow completion. No dispatch occurred in preparation;
merge is serialized after independent exact-head review and CI.
