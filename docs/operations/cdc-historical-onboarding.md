# CDC 2008-2021 DEV onboarding

The steward-review increment is complete. The separately approved next increment
is documented in [DEV historical full ingestion](cdc-historical-ingestion.md).

Owner-approved increment: onboard `qtbi-xd4i` for steward review. This is not
authorization to ingest all rows, approve the candidate, or change PROD.
Implements the source onboarding contract's explicit next-source sequence and
ADRs 0005/0006; preserves ADR 0018 publication controls for the current source.

## Acceptance and implementation map

| Requirement | Implementation and required proof |
| --- | --- |
| Exact publisher and era | Allowlisted source profile and identity/schema/year admission tests |
| Bounded source evidence | Collector stores metadata/documentation and at most 100 ordered sample rows in private DEV artifacts; default 25 |
| Honest assessment | Distinguish sample observations from unverified full coverage, uniqueness, suppression and geography completeness |
| Reviewable DEV candidate | Forward-only DEV migration extends queue/detail/history and controlled decision procedure for exactly two geographic CDC sources |
| Human approval | Existing steward authorization and immutable decision transaction remain; runtime cannot approve |
| Correct UI | DEV source selector with explicit era label; current-source selection and PROD behavior unchanged |
| No acquisition leakage | Full-ingestion commands remain current-source-only; historical evidence never calls RAW loading or dbt |
| Provenance | Retain resource, source URL, retrieval time, configuration/schema/artifact hashes and source-faithful values |
| Deployment | Local and hosted quality gates, DEV deployment, live restricted-view checks and review handoff |

## Initial evidence

Publisher metadata retrieved read-only on 2026-09-08 identifies `qtbi-xd4i` as
the 2008-2021 aggregate geographic dataset. It reports seven fields: year,
state, fips, case_status, sex, age_cat_yrs, frequency. Publisher documentation
warns that jurisdictional reporting practices vary and the 2022 definition
change precludes direct historical comparison. No complete dataset was fetched.

The existing collector, approval views and decision procedure are explicitly
restricted to `x5j9-wybp`; changing only the resource configuration would not
produce a reviewable candidate. Extend the bounded review path, not the current
full-ingestion/publishing implementation. Do not modify applied migrations.

## Remaining delivery

Wire the admission checks into durable evidence capture; extend DEV-only governed
views/procedure and source selection; add regression/authorization tests; deploy
and capture the candidate. Completion requires a real pending candidate visible
to the steward, not merely a passing fixture or a local configuration file.
