# Human surveillance MMG crosswalk v1 (DATA #470)

Status: draft for independent scientific/steward review. Owner: Atlas data
stewardship. [Machine-readable crosswalk](atlas-human-mmg-crosswalk-v1.json),
version 1.0.0, reviewed October 2, 2026. This is a bounded metadata annotation of
the existing #188 identities, not a second semantic layer or an adapter runtime.
Here `reviewed_on` and context status `reviewed` record source research only;
they do not record scientific/steward approval. DATA #470 remains open until
that human approval is recorded.

The [CDC catalog](https://ndc.services.cdc.gov/mmgpage/lyme-and-tickborne-rickettsial-diseases-message-mapping-guide/)
identifies Lyme/TBRD MMG v1.0.2, May 10, 2022, as current. Its workbook requires
Generic individual case notification MMG v2 for a complete notification.
The referenced common fields appear in the workbook's `Lyme TCSW` under `GenV2`;
they are not disease-specific Lyme fields. Exact workbook SHA-256, sheet and row
locators are recorded in JSON. Reproduce verification by downloading the linked
workbook, checking the hash, then inspecting rows 14, 50 and 69 of `Lyme TCSW`.

[PHIN VADS view v6](https://phinvads.cdc.gov/vads/ViewView.action?id=E700A51E-2B81-F111-BAF8-0050569763C5)
was published July 16, 2026. View version is distinct from each value-set version:
County (`PHVS_County_FIPS_6-4`, OID `2.16.840.1.114222.4.11.829`) is v7.
This is a terminology reference, not proof of membership for every Atlas county
or equivalence between historical FIPS vintages. Case-classification value-set
version/code equivalence remains unverified and explicitly unsupported.

| Existing indicator / measure | Relationship | Interpretation |
| --- | --- | --- |
| `human_disease_burden` / `case_count_floor_2023` | derived | Published aggregate frequency summed across Confirmed/Probable county-linked rows; no single raw MMG count field. |
| same / `incidence_floor_2023` | derived | Existing floor divided by existing county population, times 100,000 and rounded; no MMG incidence field. |
| same / `human_status` | not applicable | Atlas coverage/publication status; never CDC Case Class Status Code. |
| same / `state_unallocated_records_2023` | not applicable | State context repeated in county presentation; never county allocation or a raw notification field. |

Source is `cdc_lyme` / `x5j9-wybp`, resource `cdc_lyme_x5j9_wybp`,
definition v2, vintage 2023. JSON records source-native fields and the existing
transformation in `semantic_release._human_values`; dbt staging preserves
`fips -> county_fips`, `year -> report_year` and `case_status`. The semantic
source-mapping registry retains its existing REPORTED classification. Crosswalk
`derived` describes the relationship to case notifications, not a change to that
canonical origin or a claim that Atlas computed counts from individual messages.

Residence county has a narrower relationship to Subject Address County
(`PID-11.9`), with narrower coverage limited to supported Atlas county
identities. This does not mean dropping address components: Subject Address
County is already a county field. Annual surveillance year's relationship to
MMWR Year (`77992-6`) remains unresolved; `broader` is a candidate description,
not a proven equivalence or conversion. Exact assignment is not established.
Source Confirmed/Probable labels are a narrower conceptual subset
of Case Class Status Code (`77990-0`); no code translation is authorized. These
are context references attached to existing measures, not new measure IDs.
Unsupported context prevents any claim of a fully verified executable mapping.

Published floors are not complete incidence. Missing county-linked records do
not mean zero or disease absence. Unknown, suppressed and not-reported geography
remain distinct in retained source records. Current presentation combines rows
with these states and a resolvable state into one state-unallocated total; it
does not expose separate totals for those categories. That combined total cannot
restore hidden counties. The
state-unallocated implementation does not apply the Confirmed/Probable filter
used for county counts. Repeated state totals must not be summed across counties.
The existing [methodology contract](lyme-surveillance-methodology-v1.md) governs
case-definition eras and comparison; this crosswalk confers no comparability.

Nonhuman domains are explicitly not applicable in JSON. TBRD human observations,
individual clinical/laboratory details and demographic code translations are
unsupported. Atlas does not currently ingest HL7 case notifications. This work
does not implement clinical interoperability certification, a clinical-network
connection, public API behavior, database changes or production operations.

For #473/#471, retain existing source/version/run/artifact and observation/revision
identities. An eventual adapter may reference this crosswalk version alongside
existing semantic, metadata and lineage contracts; crosswalk membership is not
source authorization, eligibility proof or publication approval. Review changes
to standards, source versions, geography/time meaning and mapping limitations
before issuing a new crosswalk version; never silently repoint a pinned version.
Reconciled with the parallel #473 audit and #471 adapter-boundary draft at the
same main baseline: incidence-floor multi-source lineage and state-native
unallocated semantic adapters remain deferred #192 shapes. Describing those
existing release measures here does not complete their semantic adapters or
close the audit's real authority-snapshot replay gap.

The synthetic test example uses county `45001` with 100,000 population and
Confirmed/Probable frequencies 3 and 2: existing output is count floor 5 and
incidence floor 5.0. County `45003` has no linked row and remains null. A
suppressed-county frequency 7 with known state SC remains state context in both
county presentation rows. These are fabricated test inputs, not health data or
case messages; the example demonstrates preserved aggregation boundaries.

Validation is offline fixture/contract evidence: tests verify the identity pairs
against the existing release definitions, exact human scope, source registry,
version pins, context references, and rejection of orphan identities or false
exact mappings. No DEV/PROD replay or live-consumer acceptance is claimed.
