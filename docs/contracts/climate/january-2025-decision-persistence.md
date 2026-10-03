# January acceptance persistence

Matthew already accepted the retained NOAA/Census inputs and exact four January
definitions. This step records that acceptance; it does not request a new decision
or claim scientific certification. Original acceptance time remains unknown.

The smallest existing DEV path is `record-steward` in
`climate_source_review.py`, under the existing `OH_LYME_DEV_OWNER` identity with an
active GLOBAL steward entry. V075 remains CDC-only. The protected runtime workflow
continues to reject `record-steward`; it must never approve its own candidate.

`reconcile_january_climate_inputs.py --phase record-steward
--record-accepted-january` prepares the payload from committed acceptance and
review-packet files. It recomputes all four metadata content hashes and matches
them against the accepted pinned revisions. The operator must use an already
authorized owner connection; this command does not discover credentials or grant
privileges. Independent review and exact-head quality are required before execution.

The ledger recording action has its own current timestamp. The inherited payload
field `reviewed_at` and ledger `decided_at` refer to that recording action in this
mode. `conditions.acceptance_provenance` explicitly preserves
`original_decision_at={state: UNKNOWN, value: null}` and identifies the timestamp
basis. Neither a GitHub comment creation time nor the recording date is presented
as the original Matthew decision time. The rationale states this distinction.

Before writing, the existing transaction checks actual DEV owner identity, active
steward authority, completed retained run, both exact artifact hashes and sizes,
resource URLs, linked dataset keys and each single PENDING source version with no
approved decision. It appends two conditional decisions and two linked CONDITIONAL
source versions atomically, preserving the PENDING records and inactive resources.
An unexpected prior review, conflicting binding or failed second write rolls back.

Acceptance requires a subsequent independent read of the actual four-row decision/
source-version join, conditions, reviewer and exact hashes. Preparation, fixtures,
CI and a successful commit alone are not live ledger acceptance evidence.

This step does not publish metadata revisions, replace the review packet's unknown
review timestamp, activate sources, admit or publish observations, change grants,
or touch PROD. Publishing requires separate truthful metadata provenance, actual
environment-specific lineage and runtime checks. The service-reader probe remains
subject to independent review and its own deployment verification.
