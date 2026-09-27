# Dataset Discovery identity links v1

Owner: Atlas data platform. Consumer: standalone Dataset Discovery application.
Status: draft; V111 and the Dataset Discovery runtime role are not applied.

`DATASET_DISCOVERY.V_CANDIDATE_IDENTITY_LINKS` exposes only registered,
active catalog identities associated with a completed discovery snapshot. A
candidate matches a different active catalog resource through the same
canonical `resource_key`, the same non-null canonical source URL, or the same
catalog dataset ID. Exact key/URL matches produce `EXACT_DUPLICATE`; a shared
dataset ID with a different resource produces `ALTERNATE_DISTRIBUTION`.
The fixed consumer query filters by `discovery_run_id`, `resource_key`,
`catalog_dataset_id`, and `catalog_resource_id`, orders by relationship and
linked identity, and reads at most two rows. More than one link is
ambiguous and produces a candidate outcome without a model assertion.

The view deliberately omits URLs, full catalog payloads, raw artifacts,
rights judgments, and source-approval fields. `relationship_basis` records
which equality was observed; the linked canonical IDs make the result
auditable. A metadata checksum is **not** a content checksum. The current
governed catalog does not retain a reviewed revision or supersession edge, so
this view never asserts `MIRROR`, `REVISION`, or `SUPERSESSION`. Those remain
unknown until a source-backed link contract is reviewed and versioned.

V111 must not be applied or granted to a new runtime role before the owner and
security approval of data ADR 0041. The protected V103 recovery is a separate
prerequisite; no ad hoc schema creation or grant is a substitute for the
migration ledger. The runtime receives only a future reviewed `SELECT` grant
on this bounded view, never broad `GOVERNANCE` reads or writes. Rollback
removes the runtime grant and uses a forward migration to change the view;
existing recommendation assertions and audit records remain immutable.
