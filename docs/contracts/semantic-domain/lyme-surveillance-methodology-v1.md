# Lyme surveillance methodology and comparison v1 (Data #430)

Status: proposed for steward/scientific review. Owner: Atlas data stewardship.
Executable contract: `lyme_gap_atlas_data.surveillance_methodology`.
This is a storage-neutral extension of the [Atlas semantic domain](atlas-semantic-domain-v1.md)
and [ADR 0035](../../adr/0035-semantic-domain-identity-boundary.md). It attaches
methodology evidence to existing source/version/observation identities; it
does not create a second observation hierarchy, alter V071/V072, or publish an API.

## Evidence and bounded eras

| Era ID | Report years | Governed source family | Case-definition reference | Limits |
| --- | --- | --- | --- | --- |
| `cdc_2008` | 2008–2010 | `cdc_lyme_qtbi_xd4i` definition v2 | [CDC 2008 definition](https://ndc.services.cdc.gov/case-definitions/lyme-disease-2008/) | Report year only; jurisdiction practice not inferred. |
| `cdc_2011` | 2011–2016 | same | [CDC 2011 definition](https://ndc.services.cdc.gov/case-definitions/lyme-disease-2011/) | 2011 laboratory text update; no numerical equivalence inferred. |
| `cdc_2017` | 2017–2021 | same | [CDC 2017 definition](https://ndc.services.cdc.gov/case-definitions/lyme-disease-2017/) | Earlier local reporting modifications can still matter. |
| `cdc_2022` | 2022–2023 | `cdc_lyme_x5j9_wybp` definition v2 | [CDC/CSTE 2022 definition](https://ndc.services.cdc.gov/case-definitions/lyme-disease-2022/) | 2023 jurisdiction class is not inferred from 2022 evidence. |

The source definitions pin `COUNTY_OF_RESIDENCE`, `surveillance_year`, and
Confirmed/Probable categories. The two approved conformed sources actually
carry those categories. Source definition v2 and the governed
`data_source_version_id` must be supplied; an unknown source/version, period,
county identity, or case category returns `UNKNOWN`. The source version ID is
retained for comparison; a change cannot silently count as the same scope.
Report year is not illness onset, diagnosis, original publication, or first
availability. The [CDC surveillance limitations](https://www.cdc.gov/lyme/data-research/facts-stats/index.html)
also distinguish residence from exposure and warn that definitions changed in
2008, 2011, 2017, and 2022.

The [2022 CDC/CSTE definition](https://ndc.services.cdc.gov/case-definitions/lyme-disease-2022/)
identifies the high-incidence jurisdictions at the 2021 position statement,
and the [CDC 2022 MMWR table](https://www.cdc.gov/mmwr/volumes/73/wr/mm7306a1.htm)
identifies Alabama as a low-incidence example in 2022. The executable
registry encodes only those supported 2022 examples. It does not classify all
other jurisdictions as low incidence, project a 2022 category into 2023, or
claim that all counties in a state share a local investigation practice.
An additional classification can be supplied only as a reviewed, state-level,
year-bounded evidence record with an HTTPS reference. A caller remains
responsible for establishing the reference's authority and exact applicability.

## Comparison states and fail-closed rules

`COMPARABLE` means **case-definition scope only**, when both records have the
same era, governed source version, state, case category, revision and reviewed
jurisdiction applicability. It is not a complete-label, comparable incidence,
causal, public-claim, or point-in-time approval. `CAUTION_REQUIRED` identifies
a case-definition version change before 2022, changed reviewed jurisdiction
class, different category, or different revision. `NOT_COMPARABLE` is returned
for a pre/post-2022 comparison with reviewed jurisdiction applicability and
the same jurisdiction class because the revised definition materially changed
reporting. `UNKNOWN` covers missing source or
applicability evidence, cross-jurisdiction comparison, and unsupported inputs.
Reason codes and authoritative references accompany every result. A generic
source-era flag cannot override `UNKNOWN` or `NOT_COMPARABLE`.

CDC's [2022 surveillance evaluation](https://www.cdc.gov/mmwr/volumes/73/wr/mm7306a1.htm)
explains why the change affects historical comparisons: high-incidence
jurisdictions can report laboratory evidence without additional clinical
information, whereas low-incidence probable criteria differ; earlier
jurisdiction-specific practices also varied. The report does not license a
uniform multiplier or an assertion that every 2022 increase reflects risk.
No code here recodes Confirmed/Probable, adjusts counts, rewrites source values,
or fills unknown jurisdiction periods.

## Consumer and downstream boundary

`project_methodology_comparison` emits only contract version, state, reason
codes, era IDs, jurisdiction class, references, and limitations. It excludes
source payloads, counts, physical lineage IDs, and person-level data. It is
storage-neutral internal metadata until a separate #194/API #88 review admits
public exposure. #110 can stratify candidate annual cohorts by definition
era and unresolved jurisdiction; #113 can reject unsupported cross-era panel
joins. ML #23 still decides target, cutoff, label states, and evaluation.
#431 remains responsible for observation windows, lag/alignment and as-of
availability. This contract proves none of those facts.
