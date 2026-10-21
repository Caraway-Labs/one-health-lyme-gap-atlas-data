# DATA443 Stage 2 identity recovery

The exception in failed protected run 38760286768 does **not** identify the
account as the failed field. The original condition combines user, role,
database, warehouse, region and locator hash. Its earlier successful workflow
check covers only user/role/database. It cannot establish the other three fields.

Retained protected PROD inspection 38743344162 recorded account locator SHA-256
`9d740b2d2d7445285e80aea51237b1159401d6f6e29e49b996932c74f55df328`
and region AWS_US_WEST_2. That hash is exactly SHA256(uppercase `TXB06009`), as
supplied by the owner. The DEV inspection recorded the same hash. Successful
PROD migration run 38759760757 also passed the same six-field resource guard.
These bind DEV and the protected PROD migration connection to the same owner
account; they do **not** prove the failed runtime connection's actual six values.
The failed runtime locator/warehouse/region were not retained. Do not replace the
account pin, assume default warehouse selection, or introduce a grant from this
compound error. CURRENT_ACCOUNT(), rather than account name BVB26657, remains the
correct comparison input.

The correction preserves the reviewed account pin and all six exact checks;
failures now identify the field with booleans and a locator hash, without raw
unexpected identity values. The same shared guard protects source evidence,
native capture, release schema verification and production scientific readback.
No migration, source pin, approval, publication or provenance rule changes.

## Prepared single bounded verification

Use the existing capture-prod-routine-public-evidence.yml with:

- exact new reviewed merged release_commit and matching main checkout;
- source_definition=config/sources/noaa_nclimgrid_daily_202501_prod.yml;
- identity_verification_only=true;
- existing protected production runtime identity and approval XS warehouse.

This mode skips both the normal three-field check and the capture step. It uses
existing bounded_connection login parameters, executes exactly one read-only
six-field identity SELECT, then closes with retry=False. There is no transaction
context, ALTER SESSION statement, SHOW, source request, Spaces write, catalog
registration or mutation. Deadline 180s +15s grace; statement60 / queue10 /
network65 / socket65. Existing production reviewer approval is required.
A visibility error remains READ_OR_ACCESS_UNAVAILABLE, not object absence.

## Recovery authorization boundary

No new paid execution is authorized by this change. The $200 approval expressly
forbids retrying failed stages; its contingency is a retained-release rollback,
not a failed source-evidence retry. Do not rerun 38760286768 or Stage 1.

Request one new recovery allowance **within the existing $200 ceiling**:
one identity-only session/SELECT (forecast $2.90625, max $7), then **only if all six
fields match**, one new bounded Stage 2 capture attempt at the reviewed correction
(forecast $2.90625, max $7), preserving original pinned inputs and 180s+15s limits.
Any mismatch stops; no account replacement, role/warehouse changes, grants or
further retry is included. A confirmed warehouse/access issue needs its actual
owner action identified from this result, not a guessed infrastructure change.

Conservative combined recovery forecast $5.8125 / maximum $14. Baseline planning
forecast $136.50 + recovery forecast = $142.3125; baseline plus full new recovery
reservation = $150.50, below the $200 ceiling by $49.50. These are planning
reservations, **not verified unspent dollars**. Actual billed costs for completed
Stage 1 and failed Stage 2 are unavailable; do not invent remaining metered budget.
Existing public $2/credit assumption is not contractual billing evidence.

After a successful, separately authorized source-evidence attempt, continue the
two actual owner-only admissions, native capture, candidate build, publication
and both Data/API acceptance gates through the already reviewed routes. V151/V152
remain applied, V150 excluded. No historical ingestion or API activation from
Data-role evidence.
