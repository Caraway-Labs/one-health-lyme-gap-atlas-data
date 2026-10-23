# DATA #111: bounded Maryland-first Lyme label source qualification

Research receipt: 2026-10-04 UTC. This is a source-qualification record for
[DATA #110](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/110),
following [PR #598](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/598)
and [ML #86](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-machine-learning/issues/86).
It applies the separate [methodology](../contracts/semantic-domain/lyme-surveillance-methodology-v1.md)
and [temporal alignment](../contracts/semantic-domain/temporal-alignment-v1.md)
gates. No label, target, source, denominator, or panel is admitted or acquired.

## Maryland source-evidence qualification

**Disposition: DEFER.** The exact [2011–2022 MDH PDF](https://health.maryland.gov/phpa/OIDEOR/CZVBD/Shared%20Documents/Lyme%20Disease%20Data%202011%20to%202022.pdf)
still returned HTTP 404 in PR #598; its bytes and SHA-256 remain unknown. A
publisher-controlled **replacement**, [MDH/CZVBD, *Lyme Disease in Maryland by
Jurisdiction 2012–2023*](https://health.maryland.gov/phpa/OIDEOR/CZVBD/Shared%20Documents/Lyme%20Disease%20Data%202012%20-%202023.pdf),
was directly retrieved with HTTP 200 at **2026-10-04 04:39:40 UTC**. Its receipt:
**129,774 bytes**, SHA-256
`3ace977c07bc17bfcdfff8bd640fabdb0f95f00784f2164be4febf82c9d86afa`,
`application/pdf`, HTTP Last-Modified `2025-04-30 18:56:05 GMT`, ETag
`"{FC2842C2-6FA6-4A72-B873-61C35C78E12C},2"`. The one-page PDF identifies
MDH / PHPA / CZVBD and **Revised May 1, 2025**. PDF metadata reports
CreationDate `2025-04-30 14:41:52 -04:00`, ModDate `2025-04-30 14:41:55
-04:00`, Creator `Acrobat PDFMaker 25 for Word`, Producer `Adobe PDF Library
25.1.234`, Author `Jere Hutson`, and no title. These are this revision's
metadata, not original annual publication dates.

An independent `pypdf` parse of the retrieved bytes found **24 distinct named
jurisdictions, including Baltimore City separately, × 12 years (2012–2023) =
288 numeric county/jurisdiction-year cells**, 280 positive and 8 explicit zero.
All 12 recalculated jurisdiction sums equal the publisher's state row, in year
order: `1650, 1198, 1373, 1727, 1867, 1887, 1384, 1420, 838, 918, 2036,
2463`. The 2012–2016 slice has 116 positive / 4 zero; 2017–2019 has 71
positive / 1 zero. The 2012–2022 overlap, 24 × 11 = 264 cells, matches the
previously indexed 2011–2022 table by jurisdiction/year and all 11 state totals.
**This is not reproduction of that earlier 288-cell revision:** the replacement
omits 2011 and adds 2023. Official older [2008–2019](https://health.maryland.gov/phpa/OIDEOR/CZVBD/Shared%20Documents/Lyme%20Disease%20Data%202008%20-%202019.pdf)
and [2000–2015](https://health.maryland.gov/phpa/OIDEOR/CZVBD/SiteAssets/Pages/lyme-disease/2000-2015%20LymeDisease.pdf)
PDF paths were indexed but returned HTTP 404 on direct bounded GETs; indexed
content is not a file receipt.

The replacement labels **2012–2021 Confirmed + Probable**, with **2022–2023
Probable only** after the case-definition change. Its table has no suppression
mark or blank among the 288 parsed count cells; numeric zero is explicit. It
does not define whether the year is report, onset, or diagnosis year, nor
whether the jurisdiction is residence, reporting authority, or another
assignment. The [MDH case report form](https://health.maryland.gov/phpa/OIDEOR/CZVBD/Shared%20Documents/Maryland%20Lyme%20Disease%20Case%20Report%20Form%20MDH%204450.pdf)
collects county of residence and date reported, but it does **not** define how
this published aggregate table uses those fields. Exposure location is not
established. The revised compilation does not give first publication or
cell-level revision history. For a potential retrospective 2012–2016 outcome
window, this later revision could be fixed as an evaluation label only after
MDH confirms year/jurisdiction attribution and the label version/maturity
rule. Its publication date cannot make historical predictors eligible under
DATA #431. Do not pool 2017–2019 or 2022 with 2012–2016 by default under
DATA #430.

**Remaining blocker and action:** obtain MDH's aggregate table definition for
year and jurisdiction assignment, and an accessible publisher receipt for
the exact May 1, 2024 2011–2022 revision if 2011 is needed. Until then, use
the retrieved 2012–2023 revision only as a reproducible qualification lead.

## Pennsylvania fallback

**Disposition: DEFER.** Reuse the [PA DOH data page and its official 1980–2024
workbook](https://www.pa.gov/agencies/health/diseases-conditions/infectious-disease/vectorborne-diseases/tick-diseases/dashboard-data).
PR #598's direct workbook receipt, **435,622 bytes**, SHA-256
`9d3d5a8194db7099d9ff5f894c5b0580be292a3298c4627e847ed5847013b262`,
is prior evidence, not a fresh download here. It reproduces 67 counties × 45
years = 3,015 cells: 1,659 positive, 699 explicit zero, 657 `*` redacted.
2011–2016 has 392 numeric / 10 redacted; 2017–2019 has 200 numeric / 1
redacted. The resolved 2021 ten-zero count is not reopened.

PA publishes **dated annual county tables**, including [2017 report, August
2019](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/lyme/Lyme%20Disease%20Annual%20Report%202017.pdf),
[2018 report, August 2020](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/lyme/Lyme%20Disease%20Annual%20Report%202018.pdf),
[2019 report, October 2021](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/lyme/Lyme%20Disease%20Annual%20Report%202019.pdf),
and [2021 report, June 2023](https://www.pa.gov/content/dam/copapwp-pagov/en/health/documents/topics/documents/diseases-and-conditions/vectorborne/Pennsylvania%20Lyme%20Disease%20Annual%20report%202021.pdf).
These cover dates and tables establish distinct dated report vintages for
their own years; they do not establish the workbook's original release, an
immutable 2014–2016 workbook, first availability of every historical county
cell, or subsequent report/workbook revisions. The current workbook's
2025-09-12 core modification timestamp is not any older publication date.

The 2019 and 2021 PA report Table 3 footnotes say **case counts below five
are redacted** to protect confidentiality. The 2020 report states the same
rule and visibly shows zero and `*` as different states. Thus for those report
tables a redacted count is below five; a conservative interval is `[0,4]`
from the footnote alone, while the separately displayed zero shows zero is
not uniformly redacted. Do not infer that every `*` across all 45 workbook
years has the same rule or that every redacted value is positive without a
workbook-wide publisher contract. Exclude `*` from exact-count labels unless
a reviewed censored-label rule is separately approved. Never convert it to
zero.

The 2017 and 2021 reports' methods include **Confirmed + Probable** cases
under their then-current definitions and source PA-NEDSS. The 2021 report
separates onset-month analyses from its annual case count, but neither these
reports nor the workbook notes inspected in PR #598 formally define the
workbook's year field for all years as report versus onset/diagnosis year.
They also do not prove county of residence rather than another assignment;
none establishes exposure location. Enhanced local investigations in
2012/2014, the 2017 definition boundary, 2020–2021 COVID disruption, and
the 2022 laboratory-based high-incidence rule require DATA #430's separate
era and jurisdiction review. A fully numeric 2014–2016 slice remains only a
qualification probe, not an eligible supervised cohort or later holdout.

**Remaining blocker and action:** ask PA DOH for the workbook-wide `*`
definition by era, county and year assignment, category inclusion by era,
dated 2014–2016 source releases and historical revision/backfill ledger.
The dated 2017–2019 reports are useful vintage leads, but would each need
their own exact receipt, row comparison, maturity rule, and predictor-cutoff
test before use.

## Overall decision

1. **No** authoritative county-year source has cleared the full label source
   qualification gate. The Maryland replacement now has authenticated bytes
   for 2012–2023, but lacks the needed attribution and year definitions.
2. DATA #110 should freeze **no training source/window**. Maryland 2012–2016
   and separately 2017–2019 remain candidate source windows, not admissions;
   PA 2014–2016 is a fallback probe only.
3. DATA #113 remains **blocked** for a bounded point-in-time predictor panel.
   First-publication, exact predictor revision, complete-input, geography,
   and January 1 cutoff receipts must be tested independently after a label
   and denominator contract is selected. A later outcome revision is not a
   historical predictor receipt.
4. The exact missing source evidence is MDH aggregate attribution/year basis
   (plus the May 2024 file if 2011 is retained), or PA's workbook-wide
   attribution/year/suppression contract and relevant immutable vintages.
5. Stop this bounded search. Route the precise publisher questions to MDH and
   PA DOH; in parallel, return to Product/ML #23 for the reported-burden proxy
   and holdout decision. Do not continue open-ended source expansion.

These counts are surveillance-reported outcomes, not true incidence,
individual risk, exposure location, or evidence of a surveillance intervention's
benefit. The one-state leads cannot establish national generalization.
