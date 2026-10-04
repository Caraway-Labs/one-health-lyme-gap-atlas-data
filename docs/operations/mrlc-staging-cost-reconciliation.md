# DATA594 shared-cap reconciliation before execution

User-approved ceiling is **$10 total attributable acquisition/staging exposure**,
including prior attempts, with existing subscriptions/identities only. This is
an incremental operation forecast: the existing Spaces $5/month subscription and
fixed-size DEV worker continue unchanged and are not newly purchased by this
operation. This forecast does not purport to cap the unrelated whole-account
bill. No new subscription, credential, grant, worker or Snowflake operation is
permitted. Invoices/account usage allowances have not been inspected; actual
billing is unknown. All allowances are conservatively assumed exhausted for
marginal transfer/storage estimates.

## Retained attempt evidence

| Attempt | Requests / bytes known | Outcome and remaining exposure |
| --- | --- | --- |
| Earlier DATA444 bounded source metadata/ranges | Retained proof XML 34,679 bytes and two 65,536-byte TIFF headers; bounded listings/HEADs; no full raster | Early metadata count not reconstructed here; included in prior-exposure allowance, not called zero |
| Post-approval official S3 manifest preparation | 1 listing + 6 HEADs | No full body GET; nine including following failures |
| 2026-10-03 capture 16:48:54–16:48:56 UTC | At most 1 source HEAD; zero body GETs/bytes | First version HEAD 403, no files; stopped |
| Source diagnostic | 1 source HEAD | Same 403, zero body GETs/bytes; stopped |
| First canary shell invocation | 0 provider requests | CRLF shell failure before execution |
| 2026-10-03 canary 16:48:11–16:48:17 UTC after LF normalization | 5 Spaces calls, two tiny private objects retained | Verified PreconditionFailed and original full-hash readback; no raster writes |
| Offline request audit | 0 source network requests | Verified payer/signature/endpoint/version serialization; stopped before send |
| 2026-10-04 MRLC preparation | 3 HEADs + 3 conditional ranges; 196,608 bytes | Public HTTPS, zero full packages |
| Review reproduction and parser regressions | 0 source/provider requests | Virtual sparse file and fixture ZIPs only |

Actual failed HEAD request IDs were not retained, and the billed party/cost of
403 responses is not asserted. The prior allowance covers bounded metadata
charges including early ranges; no paid source-body retry is outstanding or
launched. The same $10 applies to any eventual resumed attempt. No captured
national bytes or private raster/package Spaces PUTs currently exist.

CI audit on 2026-10-04 selected 14 task branch/main Quality runs: 36.7 aggregate
run-wall minutes, 44 rounded run-wall minutes. This is timing metadata, not billed
minutes. Repository visibility is PUBLIC and Quality uses `ubuntu-latest`
standard runners, so those Actions minutes are free under the current official
billing rule. Local Docker/pytest runs use the existing laptop; no cloud runner
or custom image storage was purchased. Any later change to repository visibility
or runner class invalidates this assumption and needs budget reconciliation.
Sources: https://docs.github.com/en/billing/concepts/product-billing/github-actions
and https://docs.github.com/en/billing/reference/actions-runner-pricing .

## Explicit fixed $9 reserve

| Allocation inside the $9 | USD reserved | Basis / limitation |
| --- | ---: | --- |
| Retained original ZIPs and small immutable receipts | 6.70 | 4,269,391,159 bytes at $0.02/GiB-month for 84 months = $6.679983, assuming all bytes exceed included storage; receipts fit rounding buffer |
| All prior bounded source metadata/ranges and tiny canary objects | 0.01 | Conservative allowance above observed request/small-body exposure; actual invoice unknown |
| New worker/subscription, standard public CI, Snowflake | 0.00 | None created; existing fixed-size worker/image and Spaces subscription unchanged; public standard CI free; Snowflake operations zero |
| Ancillary uncertainty / retained-rate deviation contingency | 2.29 | Reserved, not spent or a license for another transfer/run |
| **Total fixed reserve** | **9.00** | Includes past exposure; it is not another $9 on top of prior costs |

The 84-month figure is a **finite current-rate illustration**, not an approved
retention change, prepaid price guarantee, indefinite billing commitment or
automatic deletion schedule. No storage policy/ACL/lifecycle changes are made.
Existing governance determines retention; the owner must review ongoing marginal
storage usage if required retention or future prices exceed this reservation.
Stop rather than claiming the original $10 can fund unlimited retention. Do not
retain another full package revision or expanded raster copy without reconciling
the cap. Source: https://docs.digitalocean.com/products/spaces/details/pricing/ .

The separate **$0.805236073** envelope is `4,269,391,159 / 2^30 * $0.20 + $0.01`
for combined bounded relay/upload/readback transfer and requests. Public MRLC
HTTPS has no AWS requester-pays charge. The combined rate deliberately exceeds
current marginal Spaces/Droplet transfer rates and does not assume available
included outbound allowance. Transfers use existing local/network routes and no
paid third-party relay. No new compute subscription or package extraction spool.

**Forecast total $9.805236073; unallocated difference $0.194763927.** This is a
reserved ceiling scenario, not $9.805 already incurred. The $2.29 uncertainty
contingency is already inside $9; do not add a second prior-cost amount outside
the forecast or present that contingency as measured spending.

## Required execution check

Before one bounded capture/relay/stage attempt: independent revised-head review,
green exact-head/merged-main CI, fresh existing worker loaded/inactive/cached-image
and disk checks, source manifest agreement, this prior-exposure reconciliation,
and no new cost-bearing identity/infrastructure/retention route. One attempt
permits exactly three packages, one source-body pass and one destination full
readback pass plus 64 KiB receipt allowance; 34 calls and 1800-second hard phase
deadlines. Record UTC starts/ends, requests, actual byte counts, hashes and receipts.
No automatic paid retry. After failure, reconcile actual partial transfer and
remaining reserves before a new attempt; block if a defensible total <=$10 cannot
be maintained. Report actual usage separately from unmeasured invoices. Snowflake
remains plan only even if storage staging eventually verifies completely.
