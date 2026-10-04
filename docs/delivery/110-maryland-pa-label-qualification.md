# DATA #110: bounded Maryland-first Lyme outcome qualification

Research completed 2026-10-04 UTC. This is a source-qualification record, not a
source approval, ingested dataset, eligible panel, production label, or model
target. It follows [ML #86's merged artifact](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-machine-learning/blob/11aa8d3b7e117d2917a9c0e0c41800510a824ff3/docs/eda/86-phase1-label-feasibility.md),
[DATA #430](../contracts/semantic-domain/lyme-surveillance-methodology-v1.md),
and [DATA #431](../contracts/semantic-domain/temporal-alignment-v1.md).

## Maryland label qualification

**Disposition: DEFER.** The exact official PDF could not be retrieved as bytes;
its source receipt and independent file-level reproduction are unproved. A
search-engine index of that exact official URL exposes the full table. I
independently parsed its 24 rows and 12 year columns and recalculated the
counts and state totals below. This index-level calculation corroborates the
earlier review but cannot substitute for a content-addressed publisher receipt.
No Maryland cell is admitted as an experiment label here.

| Field | Finding |
| --- | --- |
| Source | Maryland Department of Health, Public Health Services Administration, Center for Zoonotic and Vector-borne Diseases, [*Lyme Disease in Maryland by Jurisdiction 2011–2022*](https://health.maryland.gov/phpa/OIDEOR/CZVBD/Shared%20Documents/Lyme%20Disease%20Data%202011%20to%202022.pdf). Exact URL was tried with a bounded direct GET on 2026-10-04 UTC and returned HTTP 404. ML #86 also recorded 403/404. Search indexing of the same official PDF provides text, not authenticated bytes. |
| File/content receipt | **UNKNOWN**: no byte size or SHA-256 can be claimed. The indexed document says “Revised May 1, 2024”; this is a compilation revision, not an original 2011–2022 publication schedule. The direct failure is an access finding, not a zero or missing source count. |
| Period and jurisdictions | Indexed table covers 2011–2022, with 24 jurisdiction rows including Baltimore City separately from Baltimore County. Jurisdiction-name-to-FIPS mapping was not verified in this task. |
| County-year N and value states | Independent **search-index** calculation: 24 × 12 = 288 numeric cells, 279 positive, 9 explicit zero, 0 suppressed/missing in the indexed matrix. This matches the reviewer, but is not independently reproduced from official PDF bytes. |
| 2011–2016 | Index calculation: 144 numeric, 139 positive, 5 zero. Primary 2011-definition-era candidate only; no eligible training rows admitted. |
| 2017–2019 | Index calculation: 72 numeric, 71 positive, 1 zero. Separate 2017-definition-era replication candidate; do not pool with 2011–2016 by default. |
| 2020–2022 | Index calculation: 72 numeric, 69 positive, 3 zero. 2020–2021 pandemic reporting effects require separate handling; indexed PDF explicitly changes 2022 to probable-only, so 2022 is a separate definition regime. |
| Annual totals | Indexed state row displays 2011–2022 totals of 1,352; 1,650; 1,198; 1,373; 1,727; 1,867; 1,887; 1,384; 1,420; 838; 918; 2,036. **All 12 independently calculated county-column sums match the indexed state row.** This remains index-level corroboration, not a publisher-file reconciliation. |
| Outcome semantics | PDF footnote says Confirmed and Probable cases were reported to CDC for 2011–2021; 2022 is Probable only after Confirmed was eliminated. The title and table identify jurisdiction-year counts, but do not establish whether each year is report, onset, or diagnosis year. |
| Residence/exposure | The indexed table does not explicitly establish county of residence or exposure. Do not transfer CDC source semantics to this state compilation without Maryland documentation. |
| Methodology-era status | DATA #430 separates 2011–2016 from 2017–2021 and 2022 onward. The Maryland compilation does not by itself prove jurisdiction-specific surveillance practice or same-source-version comparability under the executable contract. |
| Publication/revision status | Current compilation revised 2024-05-01. Initial release dates and cell-level revision history remain unknown. A late *outcome* revision can be used in retrospective evaluation if its maturity/version rule is fixed; any prior outcome used as a *predictor* still needs availability at the historical cutoff. |
| Major limitations | Missing PDF receipt/digest; unknown year and attribution basis, FIPS mapping, historical vintages, and local investigation changes; one-state scope; reported burden is surveillance-captured and affected by ascertainment. |
| Point-in-time implication | No historical predictor row becomes eligible merely because these later outcomes appear complete. DATA #113 must independently test first publication, exact input revisions, support, and decision-cutoff eligibility under DATA #431. |
| Recommended next action | Maryland publisher/owner supplies an accessible official PDF or content-addressed official copy of this exact revision, plus table definitions for residence and year basis. Re-run 24 × 12 cell and 12 state-sum checks before selecting this source. |

## Pennsylvania fallback

**Disposition: DEFER.** The official source is reproducible and is the bounded
fallback for further qualification. Its observed numeric cells are source
counts, not an admitted Phase 1 label cohort.

| Field | Finding |
| --- | --- |
| Source | Pennsylvania Department of Health [dashboard data page](https://www.pa.gov/agencies/health/diseases-conditions/infectious-disease/vectorborne-diseases/tick-diseases/dashboard-data) and linked [*OfficialLymeByReport2024withMap.xlsx*](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/vectorborne/OfficialLymeByReport2024withMap.xlsx), sheet `RedactedCountyCaseCounts`. |
| File/content receipt | Direct GET completed 2026-10-04 04:06:00 UTC; 435,622 bytes; SHA-256 `9d3d5a8194db7099d9ff5f894c5b0580be292a3298c4627e847ed5847013b262`, identical to ML #86. Workbook core properties: created 2015-06-02 22:28:57, modified 2025-09-12 18:36:28, stale title “1980-2021 Lyme Disease Data.” None proves public first-release timing. |
| Period and jurisdictions | 1980–2024, 67 unique named PA counties, 45 year columns. County names have not been mapped to a reviewed vintage-specific FIPS set. |
| County-year N and value states | 3,015 cells: 2,358 numeric (1,659 positive and 699 explicit zero), 657 `*` suppressed, 0 blank/missing in the displayed 67 × 45 matrix. `*` means counts below five are not displayed; it is never zero. The publisher's exact suppressed-value interval, including whether zero can be redacted, needs clarification. |
| 2011–2016 | 402 cells: 389 positive, 3 explicit zero, 10 suppressed; 392 numeric. By year, numeric/suppressed: 2011 62/5, 2012 64/3, 2013 65/2, 2014–2016 each 67/0. Butler, Delaware, and York had enhanced surveillance in 2012 and Allegheny in 2014, so source-specific county effects remain even inside the 2011 definition era. |
| 2017–2019 | 201 cells: 200 positive, 0 explicit zero, 1 suppressed (2019). Treat as separate 2017-definition-era replication candidate; a presence/absence classifier would be nearly trivial. |
| 2020–2024 | 2020–2021: 134 cells, 95 positive, 12 zero, 27 suppressed; workbook and [2021 report](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/vectorborne/Pennsylvania%20Lyme%20Disease%20Annual%20report%202021.pdf) flag pandemic effects. 2022–2024: 201 cells, 200 positive, 0 zero, 1 suppressed; 2022 high-incidence laboratory-only definition is a material break. |
| Outcome semantics | Workbook says PA-NEDSS/Vital Statistics, investigated cases counted officially, and filename says “ByReport”; the [2021 report](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/vectorborne/Pennsylvania%20Lyme%20Disease%20Annual%20report%202021.pdf) explicitly includes Confirmed and Probable under then-current CSTE/CDC definitions. The workbook itself does not encode category-specific counts or a formal year-field definition for all 45 years. Do not silently call onset or diagnosis year report year. |
| Residence/exposure | A county of cases is displayed, but the inspected workbook notes and 2021 report table do not explicitly prove residence rather than another county assignment for all years. Exposure location is unproved and must not be inferred. |
| Methodology-era status | DATA #430's 2011/2017/2022 definition boundaries apply as qualification questions, not automatic `COMPARABLE` outputs for the PA workbook. Local enhanced investigations, 2020–2021 disruption, and 2022 change prevent blanket pooling. |
| Publication/revision status | The report is cover-dated June 2023; current workbook core modification is September 2025. Neither provides archived county-cell first publication or complete revision lineage. The 2021 PDF receipt in this task is 2,239,816 bytes, SHA-256 `9785d2894456444a237db8962f51d57eff4a57109aa060e3de684c50064a579b`; direct GET completed 2026-10-04 04:06:46 UTC. |
| Major limitations | One-state coverage; suppressed cells; county attribution/year semantics and historical vintages unresolved; investigative resources and provider reporting vary. No exact case-rate label without a governed same-year population denominator. |
| Point-in-time implication | Later final outcome publication does not invalidate retrospective testing. Historical *predictors*, including any lagged Lyme count or population input, must have evidenced first publication, revision, and completion by the forecast cutoff under DATA #431. No such eligible panel has been demonstrated. |
| Recommended next action | Obtain PA DOH's definitions for county assignment and report year, suppression interval, and dated pre-2017/pre-2020 workbook or report vintages; then DATA #113 can test a tiny 2014–2016 same-era, fully numeric **candidate** cohort against historical predictor receipts before considering a broader panel. This three-year slice is a qualification probe, not a sufficient train/holdout design. |

### 2021 report/workbook reconciliation

The ML #86 artifact said the report had nine zero counties versus ten in the
workbook. Visual inspection of [the official 2021 report, page 8, Table 3](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/vectorborne/Pennsylvania%20Lyme%20Disease%20Annual%20report%202021.pdf)
finds **ten**, exactly the workbook's Columbia, Forest, Greene, Juniata,
Lebanon, Mifflin, Montour, Schuylkill, Snyder, and Sullivan. This resolves the
*zero-county-count* discrepancy as an earlier reading/counting error; it does
not prove the 2021 county values or all annual vintages immutable. Both sources
show 19 suppressed 2021 counties. The workbook's 48 numeric county cells sum to
2,853; the report's statewide 2,900 leaves 47 cases across those suppressed
cells, consistent with but not a proof of a specific suppression rule. No
suppressed county is allocated or filled.

## Overall recommendation and handoff

1. **No bounded supervised experiment is authorized yet.** PA establishes a
   reproducible county-year reported-count lead; Maryland remains the preferred
   unsuppressed lead only if its exact publisher receipt and semantics are
   independently reproduced. Neither establishes a supervised Phase 1 proxy,
   historical predictor eligibility, or a later untouched holdout.
2. ML #23 should freeze **no** source/window for training now. For the next
   qualification test, DATA #113 can use PA 2014–2016 as a *candidate*
   fully numeric, same-definition-era probe, subject to PA attribution/year
   definition, exact source vintage, geography and forecast-cutoff evidence.
   If Maryland receipt is recovered, prioritize its 2011–2016 and separately
   2017–2019 cohorts for the same test. Do not pool eras or claim those windows
   are adequate for validation merely from cell counts.
3. The exact blockers are Maryland receipt and attribution/year semantics; PA
   source-vintage/attribution/suppression evidence; source-specific methodology
   comparison; historical predictor publication/revision/completion receipts;
   and ML #23's approved reported-burden proxy and holdout plan.
4. The smallest next action is publisher clarification/recovery for Maryland's
   exact 2024-05-01 revision and PA's historical workbook definitions/vintages,
   followed by a few-row DATA #113 as-of probe. This document hands the source
   contract to DATA #113 but **does not unblock** a point-in-time panel test
   until those specific source and predictor receipts exist.

Reported cases represent surveillance-captured reported burden. They are not
true incidence, individual risk, exposure location, or evidence that more
surveillance would improve outcomes.

## Reproduction and evidence boundary

- ML #86 already committed the [bounded PA workbook profiler](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-machine-learning/blob/11aa8d3b7e117d2917a9c0e0c41800510a824ff3/scripts/research_86.py): run `uv run --no-sync python scripts/research_86.py --pa` in that repository at the linked commit. This task independently re-read the publisher workbook with `openpyxl` in memory, checked its exact sheet/year/county rectangle and value states, and compared its SHA-256 with ML #86. No raw extract is committed.
- Maryland: one exact official URL GET with a browser user agent, 30-second timeout, returned 404. A search-engine index of that exact official URL was parsed for the 24 named rows and 12 annual columns; cell signs and column sums were recalculated against its displayed state row. Search-index text is derivative and mutable, so a future receipt must capture UTC retrieval time, byte count and digest, parse all 24 rows and 12 annual columns, reject duplicate/blank/non-numeric cells, and match every state total before changing the disposition.
- PA 2021: direct official PDF GET, SHA-256 above; rendered page 8 and visually counted named zero/suppressed rows. This is a targeted correction to the ML #86 review, not a claim that all county values or revisions were reconciled.
- Evidence is publisher-current direct-file and indexed-page evidence. No Snowflake, PROD, source acquisition, ingestion, model training, or historical eligible panel was run. The two source files were retained only in the operator's temporary directory for local verification.
