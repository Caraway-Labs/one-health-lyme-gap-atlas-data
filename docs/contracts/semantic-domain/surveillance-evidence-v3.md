# DATA429 source-qualified Reported interpretation v3

Status: candidate under the [delegated implementation decision](../../delivery/data429-decision-packet.md).
Formal canonical contract-steward approval, reviewed live metadata and consumer
admission remain separate gates. No approval record or activation hook is added.

`atlas-surveillance-evidence-v3` retains v2's five tokens and bounded rules,
including the contradictory NEON evidence abstention. Its only newly supported
classification is `detected_below_establishment`, meaning **Detected;
establishment criteria not documented as met in the source.** Historical v2
interpretations remain attributed to v2; the implementation now emits v3 rule
and evidence revision identifiers. Existing #188 observations are unchanged.

Eligibility is the exact `Reported` publisher value, `county_tick_status`,
`scapularis_status` (*Ixodes scapularis*), definition 1, vintage 2025, county
grain and `CUMULATIVE_THROUGH_DATE` endpoint 2025-12-31, with validated lineage
to `cdc_arbonet_tick_module` / `cdc-ixodes-county-status-2025` and workbook
SHA-256 `e35a5066a7c77b2e79c50f315a18e042405ab7baa8a414a1a907792bb25d2adc`.
Other artifact hashes/source tuples/dates abstain. The workbook is
`Public_Use_Ixodes_County_Table_2026_03252026.xlsx`, `Ixodes records 2025`.
The existing mapper validates source version, run, artifact, record and
reviewed metadata before the rule; no caller approval boolean selects a state.

[CDC's dataset page](https://www.cdc.gov/ticks/data-research/facts-stats/tick-surveillance-data-sets.html)
connects the exact workbook to cumulative categories.
[Eisen et al. 2016, page 2](https://stacks.cdc.gov/view/cdc/39097/cdc_39097_DS1.pdf)
includes historical Reported records with undocumented count/stage. No numeric
threshold is computed. Count, stage, collection date and effort remain missing;
the endpoint is not a 2025 collection event. No current ecological
non-establishment or sampling completeness is inferred. Pathogen `Present`,
*I. pacificus*, site/event detections and other taxa are not expanded.

The consumer companion retains the qualified meaning as explicit limitations,
the v3 contract/rule version and revision-bound legacy lineage. Public/live
admission remains subject to existing gates. Private proof and restricted raw
fields remain excluded. Local workbook rule probes are not governed canonical
replay unless genuine metadata and authority inputs are supplied.
