# Requirements: Snowflake Streamlit Source Approval Console

## Summary

Build a Streamlit in Snowflake application named `SOURCE_APPROVAL_CONSOLE`. It is the mandatory human-review gate between automated catalog discovery/source assessment and full source-data ingestion.

The application must allow authorized data stewards to inspect discovered catalog resources, their metadata/documentation/sample evidence and deterministic assessment scores, then approve, conditionally approve, reject, retire, or defer the candidate. Every decision must create an immutable, attributable `GOVERNANCE.MANUAL_REVIEW_DECISIONS` record and control whether the DigitalOcean pipeline may create a full-ingestion run.

The MVP uses Snowflake Streamlit’s **warehouse runtime with owner’s rights**. It runs in Snowflake, does not call external networks, and uses Snowflake identities/roles for access. It is part of the governed pipeline—not a general-purpose data exploration app.

## Business problem to solve

Automated discovery finds useful candidates but also returns mirrors, documents, inaccessible endpoints, unsupported formats, stale datasets, and sources whose terms or methodology require judgment. Automatically pulling every result into Snowflake would create cost, quality, licensing, and public-health-semantic risk.

The console provides an accessible, auditable way for a data steward to decide whether a source is appropriate for full ingestion. It must make the decision evidence visible without granting stewards direct write access to governance tables or allowing an unreviewed source to enter downstream data products.

## Scope

### In scope

- Review and decision workflow for catalog-discovered source candidates in `ONE_HEALTH_LYME_GAP_ATLAS_DEV` and `ONE_HEALTH_LYME_GAP_ATLAS_PROD`.
- Read-only display of catalog metadata, resource classification, source documentation snapshots, schema/sample summaries, deterministic assessment results, and prior decisions.
- Creation of approval decisions and approval conditions through a controlled Snowflake stored procedure.
- Audit display, filtering, and drill-down for candidates, decisions, and blocked issues.

### Out of scope

- Running discovery, full ingestion, transformations, retries, or backfills from the UI.
- Editing raw payloads, artifacts, scores, source metadata, or historical decisions.
- Direct external API calls, external-network access, stored API keys, or DigitalOcean credentials.
- Controlled-data approval, data-use-agreement management, or patient-level data access.

## Deployment model

| Item | Requirement |
|---|---|
| Application | `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>.GOVERNANCE.SOURCE_APPROVAL_CONSOLE` |
| Runtime | Snowflake Streamlit warehouse runtime with owner’s rights |
| Application owner role | `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_STREAMLIT_OWNER` |
| Query warehouse | `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_APPROVAL_XS_WH`, auto-resume and 60-second auto-suspend |
| Network access | None; do not configure external access integrations or app secrets |
| Environments | Deploy the same versioned application to `ONE_HEALTH_LYME_GAP_ATLAS_DEV` and `ONE_HEALTH_LYME_GAP_ATLAS_PROD`; development uses fixtures/synthetic candidates only |
| Source control/deployment | App source, `snowflake.yml`, SQL migrations, and tests live in the implementation repository. GitHub Actions deploys after required checks pass. |

The Streamlit object must be owned by the dedicated owner role. Viewer roles must receive only `USAGE` on the app and no `WRITE`/`OWNERSHIP` privilege on its source files or underlying governance tables.

## Roles and authorization

| Role | Permissions and responsibilities |
|---|---|
| `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_STREAMLIT_OWNER` | Owns the app and controlled review procedure; receives only the minimum read/write permissions required for the console’s governance objects. It is not the pipeline service role. |
| `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_DATA_STEWARD` | May use the app and submit source-review decisions. Does not receive direct `INSERT`, `UPDATE`, `DELETE`, or table-admin rights on governance ledger tables. |
| `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_APPROVAL_VIEWER` | May use the app in read-only mode, inspect approved/rejected decisions and candidate summaries, but may not submit decisions. |
| `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_PIPELINE_RUNTIME` | The DigitalOcean service-user role. It reads approved source versions and executes ingestion; it cannot approve candidates or alter Streamlit code. |
| `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_SECURITY_ADMIN` | Manages role grants, active-steward mapping, owner-role assignment, and access reviews. |

`GOVERNANCE.APPROVAL_STEWARDS` shall map an active Snowflake username to authorization scope, such as `GLOBAL`, catalog, publisher, source domain, or data classification. The app shall obtain the viewer identity only with `st.user.user_name`; under owner’s rights, SQL `CURRENT_USER()` identifies the app owner and must not be used as the reviewer identity.

## Functional requirements

### Candidate queue

**SA-1.1 — Queue visibility.** The application shall display candidates with assessment status `DRAFT`, `CONDITIONAL`, `PENDING_REVIEW`, or review-required triggers. It shall include candidates with material schema, documentation, license, methodology, access, or quality changes.

**SA-1.2 — Filtering and prioritization.** Users shall filter by environment, catalog, publisher, source domain, resource type, classification, recommended role, assessment/review status, score range, date discovered, and trigger type. Default ordering shall prioritize blocking/review-required issues, then highest readiness/relevance score, then oldest undecided candidate.

**SA-1.3 — Candidate summary.** Each queue row shall show dataset/resource title, owner/publisher, canonical URL/domain, access type, format, source classification, assessment scores, recommendation, known limitations, freshness evidence, and decision status.

### Evidence review

**SA-2.1 — Metadata evidence.** A candidate-detail page shall display the catalog record and resource metadata captured at discovery, including catalog, query term(s), catalog timestamps, canonical resource resolution, license/terms links, geographic/temporal grain, and data classification.

**SA-2.2 — Documentation evidence.** The page shall display document snapshot metadata and links/identifiers for data dictionaries, methodology, case definitions, release notes, licenses, terms, and landing pages. Large or sensitive raw documents shall not be rendered in full by default.

**SA-2.3 — Sample/schema evidence.** The page shall display the schema fingerprint, field names/types/descriptions, sample summary, source record/count evidence, and material schema changes. It must not show unredacted credentials or unapproved protected payloads.

**SA-2.4 — Assessment evidence.** The page shall show relevance, join potential, accessibility, documentation, and quality/readiness scores; each score’s evidence references; the recommended analytical role; and limitations/required caveats.

**SA-2.5 — Source-family safeguards.** For CDC Lyme candidates, the UI shall prominently show surveillance-era, geography, and line-list restrictions. It must warn that line-listed data without geography cannot be joined to county contextual facts and that cross-era comparisons require explicit methodology/review.

### Decision workflow

**SA-3.1 — Allowed decisions.** An authorized steward shall be able to select `APPROVED`, `APPROVED_WITH_CONDITIONS`, `REJECTED`, `RETIRED`, or `DEFERRED`. The UI shall not present a generic “save” action that silently changes a decision.

**SA-3.2 — Required rationale.** A decision submission shall require a plain-language rationale. `APPROVED_WITH_CONDITIONS`, `REJECTED`, `RETIRED`, and `DEFERRED` shall also require a structured list of conditions, required actions, or deferral reason.

**SA-3.3 — Approval prerequisites.** The UI shall disable `APPROVED` and `APPROVED_WITH_CONDITIONS` unless the candidate has a registered resource, supported access profile, metadata snapshot, documentation/terms evidence, schema/sample snapshot, successful assessment, and no unresolved blocking quality or material-change event.

**SA-3.4 — Controlled write path.** The app shall submit decisions exclusively through a versioned stored procedure, for example `GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION`. Direct DML from app code to `MANUAL_REVIEW_DECISIONS`, `DATA_SOURCE_VERSIONS`, or assessment tables is prohibited.

**SA-3.5 — Viewer attribution.** On submission, the app shall pass the server-provided `st.user.user_name` and selected decision payload to the procedure. The procedure shall validate the username against active `APPROVAL_STEWARDS` authorization scope before inserting the decision. It shall write the viewer’s username, submission timestamp, app version, and request/correlation ID to the audit record.

**SA-3.6 — Immutable decisions.** Submitted decisions cannot be edited or deleted. A later change shall create a new superseding decision that links to the prior decision and explains the change.

**SA-3.7 — Source-version activation.** An approval procedure may create or activate `DATA_SOURCE_VERSIONS` only for an approved decision and a completed evidence set. Rejection, deferral, or retirement must leave artifacts and assessment history retained but prevent full-ingestion scheduling.

### Audit and operational visibility

**SA-4.1 — Decision history.** Users shall see chronological prior decisions, reviewer identity, status, rationale, conditions, source-version linkage, and supersession relationship.

**SA-4.2 — Post-decision workflow.** After a governed decision succeeds, the app shall refresh the pending-review queue, show a readable confirmation, and select the next pending candidate. When none remain, it shall clearly state that the review queue is clear and explain that future discovery evidence will appear when ready.

**SA-4.2 — Pipeline impact.** The detail page shall state whether the source is eligible for full ingestion, currently active, blocked, retired, or awaiting action. It shall show the latest ingestion and quality status without allowing the app to start a run.

**SA-4.3 — Export.** Authorized users may download a CSV/JSON summary of filtered candidate/decision metadata. Exports must exclude raw payloads, artifact contents, secret references, and sensitive data.

## Data contract

The app reads from governed views rather than base tables wherever a view can limit columns or redact content. Required views include:

| View/procedure | Purpose |
|---|---|
| `GOVERNANCE.V_SOURCE_APPROVAL_QUEUE` | Candidate queue with assessment and blocking-trigger summaries. |
| `GOVERNANCE.V_SOURCE_APPROVAL_DETAIL` | Candidate metadata/resource/access/document/schema/quality evidence. |
| `GOVERNANCE.V_SOURCE_REVIEW_HISTORY` | Immutable decisions and supersession history. |
| `GOVERNANCE.V_SOURCE_PIPELINE_STATUS` | Latest run, source-version, and promotion eligibility status. |
| `GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION` | Validates steward scope; records immutable decision; activates/supersedes source version only when permitted. |

The implementation must define and test these views/procedure against the governance entities already required in `SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md`. The Streamlit app may not independently define a duplicate source registry or approval ledger.

## Security and privacy requirements

- Use a dedicated owner role, a dedicated app warehouse, least-privilege grants, and separate `DEV`/`PROD` deployments.
- Do not use external access integrations, call catalog APIs, or put secrets in app code, `st.session_state`, logs, exports, or Snowflake tables.
- Do not grant users `WRITE` or `OWNERSHIP` on the app. Changes deploy through reviewed source control and CI/CD only.
- Treat all text entered by reviewers as untrusted input: bind parameters in SQL, validate lengths/enums, encode displayed values, and prohibit dynamic SQL created from free text.
- Apply the same data-classification, masking, and retention policies that protect governance objects. Default to summaries and metadata rather than raw payload display.
- Test all role combinations. A viewer must be unable to submit, a pipeline role must be unable to approve, and a steward must be unable to alter historical evidence or app code.
- Record app access and write operations using Snowflake-native history as corroborating evidence, in addition to the custom decision ledger.

## UX requirements

- Provide a queue page, candidate-detail page, decision form, and audit/history page.
- Use clear, plain-language labels; show the decision consequence before submit, such as “Approve: allows scheduled full ingestion after deployment.”
- Require an explicit confirmation step for approval, rejection, retirement, and any decision that changes an active source.
- Keep the interface performant with paginated queries, server-side filtering, and summary-first rendering. It must not load all raw artifacts or candidate payloads into the browser.
- Display empty states, data-access errors, stale-result notices, and procedure-validation errors without exposing implementation internals or secrets.

## Non-functional requirements

- **Auditability:** every displayed decision is traceable to a candidate/resource, submitted viewer, timestamp, app release, and validation outcome.
- **Availability:** failure of the app must not cause the ingestion worker to bypass approval; it leaves candidates pending.
- **Cost control:** use the dedicated X-Small warehouse with 60-second auto-suspend; do not run background polling from the app.
- **Version control:** ship application source, SQL views/procedure, deployment configuration, and tests through the same repository/CI discipline as the pipeline.
- **Accessibility:** meet basic keyboard navigation, readable status/color contrast, and descriptive error-message expectations for internal users.

## Acceptance criteria

- A user with `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_APPROVAL_VIEWER` can browse/redact-filter candidate evidence but cannot submit a decision or directly modify governance objects.
- A user with `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_DATA_STEWARD` can submit one valid decision only through the app; the procedure records the actual `st.user.user_name`, rationale, conditions, timestamp, app version, and evidence references.
- Approval is blocked when required evidence is missing or a blocking issue is unresolved, and the error explains what must be remediated.
- An approved CDC/Socrata candidate appears as eligible to the pipeline only after the governed source version is activated; a rejected/deferred candidate never becomes eligible.
- A changed schema, methodology note, license, case definition, or quality failure appears in the review queue and prevents automatic promotion until a new decision is recorded.
- The app exposes no API keys, Snowflake private keys, raw protected payloads, or unredacted request data to viewers or logs.
- The production app is deployed from reviewed repository code, while the development app uses synthetic/fixture candidates and cannot modify production data.

## Testing

### Unit tests

- Validate decision enums, required rationale/conditions, field-length limits, parameter binding, and UI state transitions.
- Test evidence-completeness and blocking-condition logic for each decision type.
- Test CDC Lyme guardrail text and line-listed/geography restrictions.

### Snowflake integration tests

- Create fixture catalog/resource/assessment/change-event data in `ONE_HEALTH_LYME_GAP_ATLAS_DEV` and verify queue/detail views return the correct redacted records.
- Test the controlled procedure with steward, viewer, pipeline, and unauthorized identities; assert that only active stewards in scope can write a decision.
- Verify an approval activates an eligible source version only when all prerequisites pass; verify reject/defer/retire do not activate it.
- Verify decision supersession preserves the earlier record and links the replacement.

### End-to-end tests

- Deploy the app to `ONE_HEALTH_LYME_GAP_ATLAS_DEV`, load a synthetic CDC/Socrata candidate, review it as a steward, and verify the decision appears in history and changes pipeline eligibility.
- Test access with every role and confirm that app use does not grant direct table or code-write access.
- Verify that a failed or unavailable approval app leaves the candidate pending and prevents the DigitalOcean worker from fully ingesting it.

## References

- [Snowflake Streamlit security overview](https://docs.snowflake.com/en/developer-guide/streamlit/object-management/security)
- [Owner’s rights in Streamlit in Snowflake](https://docs.snowflake.com/en/developer-guide/streamlit/object-management/owners-rights)
- [Viewer identity with `st.user`](https://docs.snowflake.com/en/developer-guide/streamlit/app-development/personalization)
- [Streamlit form/write example](https://docs.snowflake.com/en/developer-guide/streamlit/getting-started/example-crud-app)
- [Streamlit deployment and GitHub Actions](https://docs.snowflake.com/en/developer-guide/streamlit/create-streamlit-sql)
