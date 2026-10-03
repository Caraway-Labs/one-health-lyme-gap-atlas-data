# DATA #384: CDC Tick Bite Data Tracker qualification

Decision: **DEFER** cross-signal admission. Evaluated 2026-10-03 for
[#384](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/384).
This delivers an evidence-based qualification stop for human review. It does
not claim that all source semantics are qualified. #173-#175 must abstain from
consuming this signal until the unresolved contract fields below are verified.
There is no ingestion implementation or new ingestion story because no SELECT
decision is made.

## Verified public product and evidence

The current [CDC landing page](https://www.cdc.gov/ticks/data-research/facts-stats/tick-bite-data-tracker.html)
links the public [Power BI report](https://app.powerbigov.us/view?r=eyJrIjoiMjljNzRkMTYtZWY4Ni00YzVlLTgyNDgtMjQ4NzFjOWVkNDY4IiwidCI6IjljZTcwODY5LTYwZGItNDRmZC1hYmU4LWQyNzY3MDc3ZmM4ZiJ9).
CDC's current [Lyme surveillance page](https://www.cdc.gov/lyme/data-research/facts-stats/index.html)
also identifies the tracker as NSSP ED data, separate from Lyme case reporting.

On 2026-10-03, anonymous headless Chromium rendered the report's landing,
Data Explained, monthly, weekly, age/sex and region panels. A separate browser
context was used; no existing user/agent browser session, credentials or
BioSense access was used. The text research tool could not render Power BI,
and an initial Edge probe returned no document. Those client limitations are
not evidence that the public product is unavailable. The successful browser
inspection supersedes that access uncertainty.

| Field | Verified finding / unresolved boundary |
| --- | --- |
| Access | Public dashboard viewing works. A documented, permitted, bounded machine-readable export/API was not verified. A viewer URL is not an ingestion transport contract. |
| Native geography | Region panel lists **Midwest, Northeast, South Central, Southeast, West** and a national total. No county data was exposed in these panels. Exact state/DC membership, geographic attribution basis and historical membership stability remain UNKNOWN. Do not digitize a map into a county allocation. |
| Measure/unit | Charts and the region footnote specify ED tick-bite visits per 100,000 ED visits. The region table uses an incidence label, which must not be interpreted as disease or population incidence. Exact denominator eligibility, facility cohort and stratum matching remain UNKNOWN. |
| Detection/method | Data Explained describes text matching for tick-related visits, not confirmed disease diagnosis; it describes regional coverage differences and coding/text limitations. It reports quality filters applied in **December 2025**, without enough detail to reproduce their cohort effects. |
| History | Landing and chart controls offer **2017-2026**. Observed 2026 regional values were rendered. Controls do not prove complete weekly/monthly coverage, stable historical cohorts or historical as-published vintages. Those remain UNKNOWN. |
| Cadence | The [U.S. Climate Resilience Toolkit](https://toolkit.climate.gov/tool/tick-bite-data-tracker) describes weekly updates. Current CDC panels display **Date Last Refreshed: 9/27/2026**. Exact refresh schedule, lag and completion guarantees remain UNKNOWN. |
| Missingness/suppression | The monthly panel marks its latest month preliminary due to incomplete data. This is not a complete missingness policy. Suppression thresholds, suppressed cells, blank versus unavailable/zero and denominator-zero handling remain UNKNOWN. |
| Revision | December 2025 quality filtering is a method/coverage comparability concern. Its retrospective effect, revision identifiers, backfill window, correction history and availability of prior releases remain UNKNOWN. No immutable historical series was acquired. |
| Observation time | Panels use month/week categories, including onset-labelled controls. The exact underlying date field, onset versus ED-visit meaning, week numbering, date boundaries and time zone remain UNKNOWN. |
| Availability time | The displayed refresh date has no verified time zone, time of day or publication semantics. First publication, exact revision availability and complete-input times remain UNKNOWN. Browser retrieval is separately observable, not historical availability proof. |

The report's methods panel and chart panels are the authority for these
product-specific observations. [NSSP's general program description](https://www.cdc.gov/nssp/about/index.html)
states that platform data can arrive within 24 hours; this is **not** evidence
that the public tick dashboard publishes a complete observation in 24 hours.
Likewise, the CDC landing page's May 2024 date is a page metadata date, not a
dataset vintage or first-publication timestamp for a 2017 observation.

## Use terms and access boundary

[CDC's agency-materials policy](https://www.cdc.gov/other/agencymaterials.html)
allows use of much CDC public-domain material with agency attribution,
non-endorsement disclosure, preservation of substantive content and notice
that it is available without charge; it also identifies third-party exceptions.
This qualification record attributes the product to CDC/NCEZID and links the
free original. CDC, HHS and the U.S. Government do not endorse Atlas through
this reference. No logo rights or access to individual-level NSSP/BioSense data
are inferred. Dataset/export-specific restrictions and supported automated
access must still be verified before a separate ingestion story is SELECTed.

## Comparison contract: blocked now, conditional later

Current outcome is **ABSTAIN** for automated concordance, discordance and
anomaly use. The following are frozen prohibitions, not a selected numeric
measure or executable admission:

- Preserve native regional observations and their exact publisher identities.
  No region-to-county division, population-weighted allocation, copied county
  values or county score inclusion is permitted.
- This signal is ED care-seeking activity detected by the publisher's method.
  It is not Lyme diagnosis/incidence, field tick abundance, pathogen prevalence,
  proof of underreporting or a causal risk estimate. Independent reporting
  mechanisms do not prove statistical independence of the signals.
- Never average regional rates into a national rate or weekly rates into an
  annual rate. A new aggregate requires compatible numerator/denominator
  inputs and an explicitly reviewed method; otherwise retain publisher totals.
- If later SELECTed, permit only within-native-region, compatible-stratum and
  compatible-window descriptive comparisons after cohort, calendar, revision,
  completeness and availability gates pass. Cross-source comparisons must
  explicitly reconcile geography and observation/availability windows, not
  compare unlike raw magnitudes or infer a biological lag.
- Abstain for suppression or unknown missingness, incomplete support, unknown
  denominator, incompatible method/cohort eras, unknown geography attribution,
  or unavailable as-of evidence. Missing/null is never numeric zero.
- The current [#431 availability contract](../contracts/semantic-domain/temporal-alignment-v1.md)
  must retain distinct observation, first publication, revision availability,
  complete-input and retrieval times. Current backfilled values cannot be
  inserted into a historical decision cutoff merely because their period is old.

## Seasonality and false-positive validation

[CDC's prevention guidance](https://www.cdc.gov/ticks/prevention/index.html)
describes year-round tick exposure and greater activity in warmer months,
April-September. That supports checking seasonal context; it does not define a
normal NSSP ED rate, regional peak, expected variance or anomaly threshold.
No empirical seasonal calibration or false-positive rate was established here.

Before #173 use, require a same-calendar-window reference with verified
historical support, geography, denominator/cohort and method compatibility.
Document the December 2025 filters and test for era discontinuities rather than
letting a method change create an alert. Validate plausible false-positive
modes: ordinary seasonal variation, changing ED denominator/participation,
coding or chief-complaint availability, care-seeking changes, revisions and
preliminary periods, and geographic attribution/travel mismatch. These are
review hypotheses and test requirements, not observed causes in this dataset.
No threshold, lag or scientific effect is invented by this qualification.

## Specific reopening evidence and #188 handoff

1. Capture authoritative geography membership and attribution definitions,
   denominator/facility/stratum eligibility, detection/version and December 2025
   filter details. Explicitly decide which method eras may be compared.
2. Verify a permitted bounded export/access path, actual earliest supported
   periods, missing/suppressed examples, coverage/zero-denominator behaviour,
   revision/backfill semantics and publication/availability evidence. Obtain
   only public aggregate evidence; do not seek restricted encounters or broaden
   credentials to resolve these public-product questions.
3. Decide a specific contextual regional measure and prospective versus
   retrospective use. Freeze its comparison/abstention contract. Under #188,
   #190's current geography enum is COUNTY, SITE_EVENT or SOURCE_ONLY_COUNTY;
   regional data needs a reviewed native-grain representation, not a coerced
   county observation. Preserve measure definition/unit/denominator, source
   version, exact native periods/strata, metadata states and source/run/artifact/
   transformation/revision lineage through the existing contracts.
4. Only after a defensible **SELECT**, create a **separate bounded ingestion
   story** before implementing code. That story must specify period/region/byte
   bounds, replay/revision handling, compatibility and #173 release gates. It
   does not become an extension of #384 or an automatic ML/score admission.

## Repository and validation receipts

The [region-panel screenshot](evidence/data384/cdc384-page-6.png) and
[public inspection manifest](evidence/data384/public-report-inspection.json)
retain bounded evidence of the displayed native regions, unit and refresh date.
The manifest gives byte counts/SHA-256 receipts for six local screenshots;
only the region panel is committed. Other screenshot captures remain local
qualification evidence. No raw browser DOM, session material or source dataset
is included. These are inspection receipts, not governed artifact registration,
source-version approval or historical availability evidence.

Branch: `codex/data384-cdc-tickbite-qualification-20261003`.
Starting refreshed main: `aab1041567e005e772c29b76ce48b4f7b3c48dc9`.
Current issue, AGENTS, portable context/source-onboarding instructions and
#188 native-grain, metadata/lineage and #431 time contracts were inspected.
Context validation passes. Existing repository and GitHub PR title searches
found no delivered tracker ingestion or qualification; they do not inspect
other agents' uncommitted work. Their branches and sessions were not modified.

This branch contains research/specification, public evidence and one exact-value
secret-scanner exception for the CDC-published report identifier. Runtime, tests, dependencies,
source configs, dbt, migrations and Dockerfile remain identical to the baseline
used for #382's full checks: lint/format, mypy, dbt parse and container build
pass; pytest **3002 passed, 2 skipped, 4 failed**, with all four existing launcher
timeout failures reproduced on unchanged main (4 failed, 2 passed). GitHub CI
on #382/#380 draft PRs passes; this does not erase the local host failures or
qualify CDC source semantics. Diff and evidence checks are recorded with the PR.

The first #384 CI run passed its runtime tests/build checks, then the pinned
Gitleaks history scan misclassified the public Power BI identifier as a
`grafana-api-key` in the inspection manifest. Anonymous report rendering and
the CDC landing-page link verify its public provenance. The exception is an
AND match on that exact identifier and exact manifest path, following existing
public-identifier exceptions in `.gitleaks.toml`; no rule or file class is
disabled. The pinned scanner then passes the reachable branch-history bundle
(561 commits, about 9.65 MB), while a different synthetic matching candidate
in the same evidence path is still detected (one controlled commit, expected
exit 1). The synthetic candidate was local-only and was not committed to this
branch. CI rerun remains the authority for the complete repository-history scan.

No data adapter, source definition, county allocation, ingestion story, database
write, deployment, PROD action, grant, ML admission or Web change is delivered.
Keep #384 open for human review of DEFER and the precise missing evidence above.
