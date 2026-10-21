# DATA #680 proactive cleanup: independent technical review

Base: approved PR #667 merge, `b1c5946c59ad7281d97c6353aabeb5153491466e`.
Review performed by a separate agent against actual implementation and offline
checks; this is not a native independent-account GitHub APPROVE.

## Finding resolved

P2: the first forward SQL draft gave the 48-hour cutoff to every joined lease,
while Python limited proactive cleanup to PROD EID. A shared copy with an
unrelated live claim could therefore pass the SQL defense earlier than intended.
Final V162 uses a LEFT JOIN and rejects out-of-scope source/environment claims,
orphan claims, malformed timestamps and non-30-day policies. Only valid EID
claims receive proactive eligibility. The historical V150 source is unchanged.

## Reviewed invariants

- Fixed 48-hour eligibility with immutable capture + 30-day lease; no operator
  knob, 304 extension or change to DEV/other-source timing.
- Raw I/O closes at the same day-28 boundary, under the existing guard, so an
  old replay/checkpoint cannot recreate deleted operational bytes.
- Exact private plan/hash, scope, all-claim checks, independent approval,
  serialized I/O, durable pending intent and idempotent retry remain mandatory.
- V162 retains owner/context, transaction, payload and committed-intent gates;
  replacement drops executor USAGE and requires fresh attestation. Historical
  attestations are preserved and filtered by the new migration hash.
- Protected migration permits only pinned V150, V162, or ordered [V150,V162];
  other pending changes remain blocked. V162 requires the V150 predecessor.
- Read-only monitor checks actual checkpoint presence and Spaces HEAD/version
  history and starts nonzero alarms at day 28; provider failure cannot be green.
- Daily cadence, bounded approval/execution/retry and missed-run monitoring are
  explicit remaining operational gates. No finite buffer promises compliance
  during an arbitrary provider outage. No schedule was activated.

Reviewer reported no remaining actionable P1/P2 in the corrected implementation.
Boundary/failure tests include exact cutoff microseconds, policy isolation,
shared claims, approval/audit failure, failed-cycle retry, physical-presence
alarms, missing credentials, failed verification and drift. Final exact-head CI
and review evidence are recorded in the PR rather than inferred from this file.
No production migration, provisioning, synthetic creation, deletion, source
registration/acquisition or API activation occurred.
