# DATA429 to API88 consumer handoff

Status: serialization handoff for accepted implementation; governed replay and
consumer admission remain incomplete. This document grants no scientific or
steward approval. See [v3 eligibility and interpretation](surveillance-evidence-v3.md).

## Existing output and identity

`surveillance_evidence_mapping.project_surveillance_evidence` produces the
`atlas-surveillance-evidence-consumer-v2` envelope with an unchanged
`atlas-semantic-consumer-v1` object and `atlas-surveillance-evidence-v3` evidence.
The outer version remains v2 because the envelope format did not change.
The [JSON schema](surveillance-evidence-consumer-v2.schema.json) describes this
existing writer and references the [legacy schema](atlas-semantic-consumer-v1.schema.json)
without duplicating its value-state domain. Bundle both schemas for offline validation.

Retain evidence state, reasons, tier, observation key, canonical revision,
value state, source rule, limitations and evidence revision together. Compare
observation key/revision/value state with the semantic observation before using
an independently transported companion; JSON Schema does not enforce cross-object
equality or verify source proof. The writer binds these fields and the private
canonical evidence to the evidence revision. Validation is no substitute for
calling the governed projector. Never publish private proof hashes, lineage IDs
or raw source output through the evidence object.

API88 must project Data outputs rather than classify source labels. In particular,
`no_qualifying_record` is not absence or a sampled negative; `unknown` evidence
does not replace the canonical value state. Preserve ZERO, NO_RECORDS, UNKNOWN,
UNAVAILABLE and the existing remaining value states. A qualifying individual
negative does not establish county representativeness. The pinned cumulative
CDC Reported interpretation is “Detected; establishment criteria not documented
as met in the source.” It establishes no numeric count, sampling completeness,
current ecological non-establishment or annual collection event.

## Other Data contracts

DATA430 supplies `surveillance_methodology.classify_methodology`,
`compare_methodology` and `project_methodology_comparison` under
`atlas-lyme-surveillance-methodology-v1`; use its
[bounded eras and review conditions](lyme-surveillance-methodology-v1.md).
DATA431 supplies `temporal_alignment.evaluate_alignment` and
`project_temporal_alignment` under `atlas-temporal-alignment-v1`; use its
[alignment evidence contract](temporal-alignment-v1.md).
Neither companion proves missing publisher dates, temporal equivalence or
jurisdiction practices. Their existence does not prove public wiring or approval.

## Remaining acceptance boundary

Synthetic serialization fixtures cover all five evidence states. They demonstrate
shape and identity preservation, not governed evidence or production availability.
The existing nonfixture mapper retains INTERNAL lineage; the consumer gate must
continue to deny it until the existing admission requirements are satisfied.
Unavailable admitted evidence must remain explicitly unavailable according to
the API's existing availability contract; do not synthesize a stronger state from
an empty response, failed gate, missing row or missing proof.

Before claiming DATA429's genuine canonical-to-consumer acceptance, obtain the
bounded retained export and authoritative ledger joins for the pinned CDC versions
and NEON run, reconcile actual measure metadata, and complete required scientific/
steward review with the actual reviewer/date. A historical NEON run receipt does
not prove an eligible individual negative. No replacement source-version identity,
approval flag or review date may be invented. Public admission and production
activation require their existing gates; this schema adds neither a runtime hook
nor a deployment requirement. API88 serialization work can use these fixtures,
but live acceptance remains blocked by that governed contract evidence.
