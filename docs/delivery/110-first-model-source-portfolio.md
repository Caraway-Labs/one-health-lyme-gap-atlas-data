# DATA #110: first-model source portfolio and sufficiency decision

**Decision as of 2026-10-05: BLOCK first-model source admission; keep #110 open.** This is a portfolio decision for the current ML #23 objective, not source approval, acquisition, or an executable training panel. The earlier annual reported-incidence candidate is retained below as a separate, second-sequence feasibility result.

## Target

[ML #23](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-machine-learning/issues/23) was resumed by Product on 2026-10-03. Its **first** job is to help public-health epidemiologists identify counties warranting greater surveillance attention. The approved order is (1) surveillance-priority prediction, (2) future reported-human-burden forecasting after the first experiment receives SELECT/REJECT/DEFER, and (3) possible combination after both are independently useful. The existing heuristic County Review Priority remains a comparator, not an approved ground-truth label.

| ML #23 contract field | Current first-objective state |
| --- | --- |
| User/decision | Epidemiologist surveillance-attention decision; objective approved. |
| Target quantity and ground truth | **UNRESOLVED.** No objective, governed surveillance-priority outcome or adjudication rule is approved. |
| Geography/time grain | County objective; exact unit/period **UNRESOLVED**. |
| Forecast origin and horizon | **UNRESOLVED** for the first objective. The old January 1 annual incidence cutoff belongs to the second objective. |
| Label source, maturity, missing/suppressed/revised treatment | **UNRESOLVED** until ground truth is defined. Existing #172 categorical triage and heuristic priority are not labels by default. |
| Primary metric, error tradeoff, validation | **UNRESOLVED**; ML #23 owns these choices. |
| Interpretation | No true incidence, individual risk, underreporting, causal effect, or agency-performance claim. Missing surveillance is not low disease burden or agency failure. |
| Disposition | **BLOCK** source admission and supervised first-model training pending the target/label decision. Bounded label feasibility can continue under the existing owner tickets. |

The unresolved label definition changes which sources are *required*. Declaring climate, tick, population, or human surveillance mandatory now would presuppose the target. For the prior annual incidence candidate only, ML #23 selected county of residence × calendar report year Y, reported Confirmed+Probable cases per 100,000, forecast at 00:00 UTC January 1 Y, with an exact mature numerator and same-county/year July 1 Census PEP denominator. That was **selected for feasibility, never approved for training**. It is not the first objective after the October 3 sequencing decision.

## Label feasibility and actual sample shapes

The [#110 current-publisher audit](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/110) measured CDC `qtbi-xd4i` (2008–2021) and `x5j9-wybp` (2022–2023), cross-checking earlier DEV county-year key counts. These are annual **county-of-residence report-year** records, not onset/exposure location or annual county totals. Confirmed and Probable are separate categories. A sum of numeric-FIPS demographic cells is a **published county-linked floor** because suppressed/unknown FIPS records cannot be assigned and no authoritative all-sex/all-age county-total row exists. Absent county-year rows are UNKNOWN, not zero; the source audit found zero `frequency=0` rows.

| Reporting-era cohort | Distinct published county-years | Distinct counties | State labels | Both C/P categories | Proven exact mature C/P county-year totals |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2008–2010, distinct earlier era | 1,160 | 467 | 34 | See #110 year counts | 0 |
| 2011–2016, former primary candidate | 2,765 | 626 | 37 | 2,472 | **0** |
| 2017–2019, separate replication candidate | 1,573 | 639 | 38 | 1,494 | **0** |
| 2020–2021, pandemic sensitivity | 947 | 578 | 34 | See #110 year counts | 0 |
| 2022–2023, changed definition/source | 1,236 | 688 | 36 | See #110 year counts | 0 |

The cohorts total **7,681 distinct published county-year keys over 16 years**; they do not establish 7,681 eligible labels. The former primary six-year cohort has 527 counties present in at least two years and 327 present in all six. For candidate consecutive-year directional reported-count transitions, the documented source-backed intervals have unknown upper bounds; **0 unambiguous transitions** were proven. State-unallocated suppressed/unknown FIPS rows cannot be assigned to counties. An unlisted FIPS/year is not a measured zero. Geography compatibility and #430 jurisdiction applicability remain to be proven per cohort.

The production semantic release's **44,016 observations across 3,144 canonical counties** is a cross-source/measure snapshot, not 44,016 independent training examples. It has no 44,016 distinct county-year label keys. The relevant unit is a unique county × target period × admitted exact label after source, era, geography and as-of gates; for the first objective that count is **UNKNOWN because its label is undefined**. The prior incidence candidate has **0 proven exact labels** from the audited CDC source, despite thousands of published keys. Source-native demographic cells, semantic observations and ML examples are separate counts.

The [Maryland/PA qualification](110-maryland-pa-label-qualification.md) is source-lead evidence only. Maryland's indexed 2011–2022 table yields 288 numeric jurisdiction-years (279 positive, 9 explicit zero), including 144 in 2011–2016 and 72 in 2017–2019, but the official PDF bytes/receipt and year/attribution semantics are unknown. PA's official workbook has 3,015 county-year cells over 1980–2024: 1,659 positive, 699 explicit zero, 657 `*` suppressed; 2011–2016 has 392 numeric/10 suppressed and 2017–2019 has 200 numeric/1 suppressed. These are not admitted training labels: PA's exact county assignment, report-year interpretation, revisions and historical first-publication remain unresolved. Neither source establishes a national or leakage-safe panel. Keep the 2011–2016, 2017–2019, pandemic and 2022+ eras separate under [#430](../contracts/semantic-domain/lyme-surveillance-methodology-v1.md).

## Denominator feasibility

The first surveillance-priority objective has **no approved rate label**, so a population denominator is **conditional**, not a first-model blocker by assumption. For the second-sequence incidence candidate, a same-county/year annual resident denominator is REQUIRED and **0 usable governed county-year denominators are proven for that target**. Governed SVI `E_TOTPOP` is 2022 ACS 2018–2022 context, not a historical annual population series. Pooled ACS 5-year estimates, current population, and present-day FIPS joins cannot silently replace historical annual denominators. The earlier #111 DEV read inventory found no visible governed longitudinal county-year population product; this is a visibility-scoped finding, not a global database absence claim.

[DATA #111](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/111) owns source research and any separately approved acquisition. Its Census PEP candidate distinguishes 2000–2010 and 2010–2020 intercensal county estimates and named 2020s vintage, each with July 1 reference date, FIPS/boundary changes and postdecade revisions. These retrospective vintages cannot be projected back to a January 1 historical forecast. Archived postcensal releases and exact availability would be needed for forecast-time inputs. Population counts and FIPS matching for an admitted county-period cohort remain **UNKNOWN** because no denominator product has been admitted or joined.

## Portfolio matrix

Classification is for the **current first objective**. `REQUIRED` is reserved for the minimum source evidence without which its target cannot be defined or evaluated. `DEFERRED` means plausible ML use but no target-dependent admission yet; `UNSUITABLE` is specific to the first target/grain and does not revoke product value. Years, timing and release states below are scoped to the cited contracts and documented audits; unspecified first-publication time is UNKNOWN.

| Source | Product value | ML classification | Reason and actual grain/period | Current state / missing evidence | Owner |
| --- | --- | --- | --- | --- | --- |
| **Governed surveillance-priority ground truth** | Would make epidemiologist decision assessable | **REQUIRED** | Exact outcome/adjudication label, county-period and maturity are undefined; no usable sample count can be computed | No approved label/source, validation target or cutoff; rights/access depend on chosen source | ML #23 |
| CDC human Lyme `qtbi-xd4i` / `x5j9-wybp` | Reported-case context with residence/report-year and suppression limits | **DEFERRED** for first objective; conditionally REQUIRED for old burden candidate | 2008–2023 annual demographic/status cells; county sums are floors; 2011/2017/2022 definition breaks, first cell publication/revision UNKNOWN | Governed source exists; 0 proven exact mature C/P county totals; do not turn published keys into labels | #111 source evidence, #430 era, #113 panel |
| Maryland jurisdiction compilation | Potential state reported-burden context | **DEFERRED** | 2011–2022, 24 jurisdictions; indexed numeric table but official byte receipt and attribution/year meaning UNKNOWN | Candidate only, not DEV-admitted; 2011–2016 and 2017–2019 separate | #111; [qualification](110-maryland-pa-label-qualification.md) |
| PA official workbook | State reported-burden context, including explicit zero/suppression | **DEFERRED** | 1980–2024, 67 counties, current workbook vintage; historical availability/revisions UNKNOWN | Publisher file reproduced, not DEV-admitted; 657 suppressed cells | #111; [qualification](110-maryland-pa-label-qualification.md) |
| Census PEP annual resident population | Rate denominator and demographic context | **DEFERRED** for first objective; conditionally **REQUIRED** for incidence | July 1 county-year, versioned intercensal/postcensal vintages; boundaries and revisions matter | No admitted DEV annual series or as-of cohort; source approval, rights/attribution review and vintage receipts pending | #111 |
| SVI 2022 / ACS population context | Cross-sectional vulnerability/population context | **OPTIONAL** | SVI uses pooled ACS 2018–2022; not an annual historical denominator; geographic/temporal lag and revisions need cutoff proof | Governed context, not rate-label denominator; availability for historical forecasts UNKNOWN | #113 if selected |
| RUCC | County rurality context | **OPTIONAL** | County classification/vintage, not a county-year outcome; boundary/vintage and publication cutoff must be pinned | Governed context; no demonstrated incremental value for first target | #113 if selected |
| CDC cumulative tick/pathogen status and approved infected-tick derived results | Explains publisher status/quality and limited derived evidence | **UNSUITABLE** as annual county prevalence or abundance; otherwise **DEFERRED** | Cumulative county status is not annual sampling; derived metric eligibility requires real numerator/testing denominator and quality | Governed county evidence, with missing/no-records/unknown distinct; exact source vintage and availability needed for any feature | #113; tick contracts |
| NEON `RELEASE-2026` collection/pathogen site events | Valuable site/event epidemiologist context | **UNSUITABLE** as county-period label or representative county feature | Site/event/plot sampling; linked county is navigation only; `NOT_COUNTY_REPRESENTATIVE`; provisional data differ from citable release | Bounded governed source; no approved representative aggregation or complete county coverage | NEON source owner; #113 if proposed |
| nClimGrid-Daily | Climate context with potential longitudinal value | **OPTIONAL** | County-day/month climate support, 2008–2023 historical depth work; complete-month, support, vintage and publication matter | Bounded DEV work exists; national historical/as-of feature panel not established | #443, then #113 |
| Annual NLCD C1.2 | Land-cover/habitat context | **OPTIONAL** | County-year raster aggregation; valid source-supported area, tile/mosaic identity and 1985 null/change semantics matter | #196 bounded foundation; #594 actively handles 2025 mosaic evidence; national/historical release not proven | #444/#594, then #113 |
| MODIS vegetation | Vegetation-condition context | **OPTIONAL** | Bounded composite/QA source; composite completion, revision and exact lag must precede cutoff | #381 bounded foundation; phenology not approved as equivalent | #113 if selected |
| Drought | Contextual environment signal | **DEFERRED** | No target-dependent need or approved lag/coverage evidence for first model | Do not create first-model ingestion dependency | #197 |
| EnviroAtlas forest fragmentation | Ecological/product context | **DEFERRED** | Static/structural measure and land-cover method differ from Annual NLCD; no demonstrated first-target need | Qualification exists, source admission separate | #380 |
| 3DEP terrain | Stable terrain/product context | **DEFERRED** | Static geography, no demonstrated first-target need or historical variability | Qualification exists, source admission separate | #382 |
| AHRF response capacity | Health-system context | **DEFERRED** | No target-dependent need or approved county-year timing/rights rule | Do not create first-model ingestion dependency | #201 |

No `OPTIONAL` or `DEFERRED` source blocks target-definition work. Classifications change only after ML #23 defines the label and an evidenced source/cutoff decision is reviewed; no source is silently admitted by this matrix.

## Minimum viable package and optional blocks

For the **first** objective the smallest package is: (1) one objective, governed county-period surveillance-priority outcome with explicit adjudication, missingness, maturity and source version; (2) canonical county identity and exact outcome period; (3) only predictor history whose observation, publication, revision and completeness precede ML #23's chosen cutoff; and (4) a temporal/geographic validation and primary metric. Which predictor family, if any, satisfies (3) cannot be selected before the target/cutoff. Existing heuristic priority can be a comparator only.

For the **second-sequence incidence candidate only**, the minimal feasibility package is exact mature annual county-of-residence C/P numerator, same-county/year PEP denominator, canonical geography/era mapping and timing receipts. A small lagged human-history block is conditional on publication evidence. Climate, NLCD, MODIS, drought, terrain and response capacity are optional experiments, not prerequisites to proving a label. CDC current public-use data fail numerator completeness; Census PEP acquisition is held until a viable numerator and owner approval.

## Point-in-time risks and exact #113 handoff

For every eventual REQUIRED source, [#113](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/113) must bind observation window, first publisher publication, Atlas retrieval, exact revision availability, complete-input time, source version/vintage, allowed lag and ML #23 cutoff under [#431](../contracts/semantic-domain/temporal-alignment-v1.md). **UNKNOWN** first publication or exact revision blocks a strict as-of claim. Source `Last-Modified`, report year and Atlas retrieval are not substitutes. Later matured outcomes may support explicitly retrospective evaluation, but cannot enter earlier predictor snapshots. #430 comparison metadata cannot repair incomplete labels, suppressed values, jurisdiction practice, or FIPS mismatch. #113 must count eligible/retrospective-only/unknown/ineligible rows separately and keep optional feature cohorts apart from the minimal package.

## GO / BLOCK / DEFER decision and downstream work

**BLOCK** first-model source admission and training because ML #23 has not defined an objective label, grain, horizon, metric or validation rule. This is not a finding that every Atlas source is unusable. The second-sequence annual incidence candidate remains **DEFER**: current CDC evidence proves 0 exact numerators, no annual governed denominator, and no historical first-publication panel. No universal sample threshold is invented. #110 remains open for an approved-target-specific sufficiency audit; the documented source classifications and counts are an interim decision, not closure evidence.

- **ML #23:** select/approve or defer an objective surveillance-priority label, cutoff, horizon, primary metric/error tradeoff and validation. Do not adopt #172's triage or the heuristic priority score as truth without review.
- **DATA #111:** only bounded missing label/source and conditional denominator research; no acquisition from this artifact.
- **DATA #113:** exact as-of panel and cohort proof after the target and source evidence exist.
- **DATA #443:** existing nClimGrid depth owner; no first-model climate prerequisite.
- **DATA #444/#594:** existing NLCD depth/distribution owners; #594's active work is external evidence only.

### Evidence, environment and reproduction

This decision reads current GitHub issue contracts and the existing [#110 label audit](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/110), [#111 source specification](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/111), [#113 panel contract](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/113) and [Maryland/PA source qualification](110-maryland-pa-label-qualification.md). The CDC counts are publisher-current bounded aggregates cross-checked to earlier DEV keys; they are **not a newly run-pinned DEV/PROD extract**. Reproduction SQL/SoQL and value-state method are recorded in #110's `CDC numerator and directional-label feasibility` section. On 2026-10-05 the read-only `snow sql -c ATLAS_DEV_READ -q 'SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();' --format json` verified `MATTHEWCARAWAY / OH_LYME_DEV_READ / ONE_HEALTH_LYME_GAP_ATLAS_DEV / OH_LYME_DEV_INGEST_XS_WH`; no new source data query, extract, Snowflake mutation or credential handling followed. Fresh run-pinned counts are a future #113 requirement after target definition. Scientific limitations, exclusions and unknowns above preclude a GO decision.
