# Requirements: Data Catalog to Snowflake Data Pipelines

## Summary

Build a governed, repeatable set of data pipelines that discovers public-health and contextual datasets from catalogs, acquires each source through its appropriate access method, preserves an immutable record of what was received, and lands source-faithful data in Snowflake. Approved data must then be transformed through `STAGING`, `CONFORMED`, and, where needed, `ANALYTICS` and `FEATURE_STORE` layers.

The pipelines must treat discovery metadata, source documentation, retrieval evidence, and data payloads as one product. A user of a downstream fact, report, feature, or model input must be able to determine the precise source version, artifact, retrieval, transformation, and caveats that produced it.

The public-data MVP begins with catalog-discovered sources such as CDC/Socrata and direct public files. Controlled, restricted, or enclave-only sources are explicitly out of scope for automated acquisition until their access approvals and operating controls are in place.

## Business problem to solve

TOPx needs to combine fragmented surveillance, environmental, geographic, and contextual data without losing the meaning or evidence behind the data. Today, a catalog listing does not reliably say whether a resource is programmatically accessible, current, complete, stable, or suitable for a particular join. Publishers can revise schemas, documentation, case definitions, licenses, and data values with little notice.

The pipelines must solve the following problems:

- Convert catalog discovery into a governed inventory of usable source resources rather than an untracked collection of manual downloads.
- Route sources through connector-specific extraction patterns instead of assuming every catalog result is a file or a common API.
- Preserve reproducible evidence for successful, failed, and partial retrievals, including paginated API calls.
- Prevent unreviewed schema, methodology, licensing, or semantic changes from silently reaching analytical products.
- Preserve public-health semantics—especially the distinction between numeric zero, null, unknown, suppressed, and not-reported values.
- Provide end-to-end lineage from downstream Snowflake assets back to the exact upstream catalog resource and raw artifact.

## Goals and scope

### In scope

- Catalog discovery and source registration from Data.gov, HealthData.gov, Socrata/ODN, CMS, and manually curated public sources.
- Resource classification and acquisition via SODA/REST APIs, ArcGIS REST services, direct files, bulk downloads, and approved Snowflake shares.
- Immutable raw-artifact retention, source-faithful Snowflake `RAW` loads, data-quality checks, manual review gates, and versioned promotion.
- Transformations from `RAW` through `STAGING` and `CONFORMED`, with optional `ANALYTICS` and `FEATURE_STORE` outputs.
- A representative CDC/Socrata pipeline delivered end to end as the MVP reference implementation.

### Out of scope for the MVP

- Automated extraction of controlled, restricted, clinical, participant-level, or enclave-only data.
- Use of a controlled dataset as if it were public, or direct record linkage across governed sources.
- Clinical diagnosis, treatment recommendations, or individual risk scoring.
- Replacing Snowflake-native governance/lineage features with custom tables; the custom ledger augments native capabilities.

## Definitions

| Term | Definition |
|---|---|
| Catalog dataset | A publisher dataset/package record discovered in a catalog. It can contain several resources. |
| Catalog resource | One distribution or endpoint within a dataset, such as an API, file, data dictionary, methodology document, or landing page. |
| Access profile | Versioned instructions for retrieving a resource: connector, authentication mode, pagination, ordering, and incremental strategy. |
| Ingestion run | One end-to-end attempt to acquire and land a resource. |
| Ingestion request | One request/page/export within an ingestion run. |
| Raw artifact | An immutable copy of a received payload, export, metadata response, or source document with a SHA-256 checksum. |
| Source version | The reviewed, governed version of a source eligible for downstream use. |
| Promotion | Allowing data to proceed from `RAW` into a downstream layer after required validation and review. |

## Functional requirements

### 1. Catalog discovery and source registry

**FR-1.1 — Catalog metadata ingestion.** The system shall retrieve and snapshot catalog metadata for candidate datasets. At minimum, it shall retain catalog name, catalog record ID, publisher, title, description, canonical landing URL, catalog publication/modification timestamps, metadata payload, and snapshot time.

**FR-1.2 — Resource-level registration.** The system shall register every discovered resource separately. Resources shall support at least `DATA`, `API`, `DOCUMENTATION`, `DATA_DICTIONARY`, `LANDING_PAGE`, and `CONTROLLED_ACCESS` classifications.

**FR-1.3 — Canonical-source resolution.** The system shall identify catalog mirrors where feasible and record the canonical first-party resource. Mirrors must not be treated as independent source versions when they resolve to the same upstream source/version.

**FR-1.4 — Source assessment.** Before production ingestion, each data-bearing resource shall have an assessment recording its owner, access status, license/permitted-use status, time and geographic grain, relevant limitations, and a decision of `APPROVED`, `CONDITIONAL`, `REJECTED`, or `RETIRED`.

**FR-1.5 — Cadence management.** The source registry shall preserve both publisher-declared cadence and observed source behavior. A catalog `modified` timestamp shall not be treated as proof that underlying data changed.

### 2. Access profiles and scheduling

**FR-2.1 — Connector configuration.** Each ingestible resource shall have a versioned access profile containing platform type, connector name/version, request method, authentication mode, format, deterministic ordering expression, pagination configuration, and incremental strategy.

**FR-2.2 — Supported access routes.** The MVP shall support direct files and Socrata SODA. The design shall permit adapters for CKAN, ArcGIS REST, CMS APIs, generic REST APIs, Snowflake shares, and manual acquisition without changing the provenance model.

**FR-2.3 — Incremental strategies.** The system shall support `ETAG`, `LAST_MODIFIED`, `UPDATED_AT`, `CURSOR`, `DELTA_FEED`, `PARTITION_DISCOVERY`, `SNAPSHOT_DIFF`, and `FULL_REFRESH` where the source supports them. A strategy must be validated for the individual resource before it is relied on in production.

**FR-2.4 — Scheduling.** The scheduler shall derive an initial check schedule from declared cadence and refine it using observed freshness, changes, and failures. One-time sources shall not be polled indefinitely without a configured change-detection reason.

**FR-2.5 — Retry behavior.** The acquisition layer shall retry only rate-limit and transient server failures using bounded exponential backoff. Authentication, authorization, schema, and other non-transient failures must be recorded and routed for review rather than blindly retried.

### 3. Reproducible acquisition

**FR-3.1 — Run ledger.** The system shall create an `ingestion_runs` record before each attempt. It shall capture the resource, access profile, trigger type, run mode, code version, timing, prior successful run, status, source update evidence, row counts, and redacted error details.

**FR-3.2 — Request ledger.** The system shall create an `ingestion_requests` record for every metadata call, sample, count, page, export, and documentation retrieval. It shall retain deterministic request sequence, endpoint, redacted parameters/headers/body, cursor or offset, retry attempt, status, response metrics, and response checksum.

**FR-3.3 — Deterministic pagination.** Paginated sources shall use a stable order and a recorded page/cursor sequence. The pipeline shall detect incomplete retrieval by comparing retrieved counts with available source counts when such counts exist.

**FR-3.4 — Sample before load.** Before a new source or changed source is promoted, the pipeline shall retrieve a sample and capture source metadata, schema, documentation, data grain, and relevant semantic rules.

**FR-3.5 — Failure retention.** Failed and partial runs shall remain queryable with their available request history and error classification. A later successful rerun must not overwrite prior evidence.

### 4. Immutable landing and RAW data

**FR-4.1 — Artifact storage.** The pipeline shall store each downloaded response, file, export, and governing document unchanged in immutable object storage or a governed Snowflake stage. It shall create a manifest when an acquisition contains multiple pages/files.

**FR-4.2 — Artifact identity.** Every raw artifact shall have a URI, artifact type, media type, byte count, SHA-256 checksum, source/run/request references, retention class, and creation time.

**FR-4.3 — Source-faithful RAW tables.** Data shall land in dataset-specific append-only `RAW` tables. Each raw record shall retain the original parsed payload in a `VARIANT` field and must not be semantically transformed during load.

**FR-4.4 — Required RAW provenance.** Every RAW record shall be linked to `data_source_version_id`, `ingestion_run_id`, `artifact_id`, source URL, redacted source query, source record ID where available, source row hash, publisher timestamps, retrieval time, and Snowflake load time.

**FR-4.5 — Value-state preservation.** The pipeline shall preserve source-provided or documented markers for null, unknown, suppressed, not-reported, and numeric-zero states. It shall never coerce these states to zero.

### 5. Schema, documentation, and quality controls

**FR-5.1 — Evidence snapshots.** The system shall store versioned metadata, schema, and source-document snapshots. Supported document types shall include data dictionary, methodology, case definition, release note, license, terms, and landing page.

**FR-5.2 — Change detection.** The system shall compare each new schema/document fingerprint with the most recently approved source version and record meaningful changes. Compatibility outcomes shall include `COMPATIBLE`, `BREAKING`, `REVIEW_REQUIRED`, and `IGNORED_WITH_JUSTIFICATION`.

**FR-5.3 — Quality checks.** The pipeline shall execute and persist results for schema, required identifiers, type/domain/range, key uniqueness, duplicate, volume, temporal continuity, freshness, row-count, and source-specific semantic checks.

**FR-5.4 — Configurable gates.** Configured blocking quality failures, breaking schema changes, and material changes to methodology, license, case definition, geography semantics, time semantics, or permitted use shall block promotion.

**FR-5.5 — Epidemiological safeguards.** Quality monitoring shall distinguish pipeline defects from plausible public-health signals. For example, an unusual low-case/high-vector-risk pattern must not automatically be treated as a failed load.

### 6. Review, source versions, and promotion

**FR-6.1 — Manual-review workflow.** The system shall support designated data-steward review for blocked or material changes. A decision shall record reviewer, rationale, decision status, conditions/actions, and the approved source version when applicable.

**FR-6.2 — Versioned approval.** Only an approved or conditionally approved `data_source_versions` record may be used as an input to promoted `STAGING`, `CONFORMED`, `ANALYTICS`, or `FEATURE_STORE` assets.

**FR-6.3 — Retention after rejection.** Rejected or deferred sources must retain their catalog, run, artifact, and quality evidence but must not be available to downstream production transforms.

**FR-6.4 — Promotion lineage.** The pipeline shall record the input source versions, code version, parameters, target object, execution reference, and quality result for every transformation run.

### 7. Snowflake transformation layers

**FR-7.1 — Schema layout.** Snowflake shall contain separate `GOVERNANCE`, `RAW`, `STAGING`, `CONFORMED`, `ANALYTICS`, and `FEATURE_STORE` schemas with documented responsibilities and role-based access.

**FR-7.2 — STAGING.** `STAGING` shall perform typed, source-specific parsing and validation. It shall not apply cross-source business semantics or discard provenance.

**FR-7.3 — CONFORMED.** `CONFORMED` shall harmonize approved source data through shared, versioned geography and time dimensions. Cross-source joins must declare their geography semantics, temporal window, and aggregation method.

**FR-7.4 — Consumer layers.** `ANALYTICS` and `FEATURE_STORE` assets shall only use approved conformed inputs and shall expose or be joinable to their source version, transformation run, input vintage, caveats, and feature definition/version where applicable.

**FR-7.5 — Lineage edges.** The system shall record lineage for direct mappings, joins, aggregations, spatial matches, and temporal-window transformations. These records must reconcile with Snowflake-native dependencies and access history where available.

### 8. Governance, security, and operations

**FR-8.1 — Governance ledger.** The system shall implement the 15 provenance entities specified in [SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md](SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md): catalog datasets/resources, access profiles, document snapshots, assessments, runs, requests, artifacts, schema snapshots/change events, quality results, review decisions, source versions, transformation runs, and lineage edges.

**FR-8.2 — Append-only evidence.** Catalog snapshots, run records, request records, artifacts, schemas, quality results, and review decisions shall be append-only. Corrections must use a recorded supersession relationship rather than destructive updates.

**FR-8.3 — Secrets and sensitive data.** Credentials, OAuth tokens, API keys, and protected values shall be stored only in approved secret-management mechanisms or Snowflake integrations. Registry tables, application logs, and `VARIANT` evidence fields shall store only redacted request details.

**FR-8.4 — Classification and access controls.** Governed Snowflake objects shall be tagged at least with `DATA_DOMAIN`, `DATA_OWNER`, `SOURCE_SYSTEM`, `PROVENANCE_REQUIRED`, `GEOGRAPHY_SEMANTICS`, `HEALTH_DATA_RISK`, and `LICENSE_CLASS`. Masking and row-access policies shall follow classification, license, agreement, and enclave requirements.

**FR-8.5 — Retention.** Artifacts, metadata, schemas, and run manifests shall be retained long enough to reproduce published outputs and satisfy source terms. Controlled data shall use a stricter retention class and remain within its approved environment.

**FR-8.6 — Operational observability.** Operators shall be able to identify failed, partial, blocked-review, late, and stale sources; see retrieved versus loaded row counts; inspect redacted request history; and trace an output to source evidence.

## Non-functional requirements

- **Reproducibility:** A published output must be reproducible from retained source artifacts, approved source versions, transformation code/version, and run parameters.
- **Idempotency:** Re-running the same source version must not create duplicate business records in promoted layers. Repeated artifacts may be deduplicated by checksum without deleting run evidence.
- **Auditability:** Every automation decision, failure, retry, quality result, and review decision must be queryable with timestamps and responsible identity where applicable.
- **Extensibility:** Adding a new source connector or source-specific RAW table must not require redesigning the governance ledger.
- **Data integrity:** Referential integrity between ledger entities must be validated in the pipeline, because ordinary Snowflake PK/FK declarations are not enforcement mechanisms.
- **Performance:** Extraction must use server-side filtering, projection, aggregation, and pagination where appropriate, while retaining sufficient request evidence to reproduce the acquisition.
- **Least privilege:** Pipeline roles and connectors must have only the permissions required for their source, stage, schema, and operation.

## Delivery milestones and acceptance criteria

### Milestone 1 — Foundation

- Create the Snowflake schemas and governance entities with comments, role grants, and validated relationships.
- Implement source registry, access-profile, artifact, run, request, schema, quality, review, version, transformation, and lineage records.
- Configure storage/stage retention and secret handling.

### Milestone 2 — CDC/Socrata reference pipeline

- Register one CDC/Socrata dataset and its documentation resources.
- Implement schema-first sampling, deterministic pagination, redacted request logging, immutable artifact storage, and a dataset-specific RAW load.
- Demonstrate both a successful acquisition and a retained failure or partial run.

### Milestone 3 — Promotion and serving path

- Implement quality gates and manual review workflow.
- Promote an approved source through `STAGING` and `CONFORMED` to one `ANALYTICS` consumer.
- Demonstrate source-to-output lineage, including checksum, retrieval time, semantics, transformation run, and caveat.

### Milestone 4 — Operational readiness

- Configure monitoring for freshness, failed/partial runs, blocked reviews, schema drift, and material volume anomalies.
- Reconcile custom lineage records with configured Snowflake-native tags, dependencies, and access history.
- Document source onboarding and incident/review procedures.

## Assumptions and open decisions

- The orchestration tool, transformation framework, artifact-storage implementation, and alerting platform are not yet prescribed; each must support the stated evidence and control requirements.
- Source-specific freshness SLAs must be configured after observing actual publisher cadence. Initial values are expectations, not guarantees.
- The exact lineage integration approach (for example, Snowflake-native lineage plus dbt/OpenLineage) must be selected during technical design, while preserving the external-source provenance ledger.
- Controlled-data onboarding requires a separate approval, data-use, security, and output-review design before it is added to automated pipelines.

## Testing

Testing must be automated where possible and must include an auditable end-to-end test of the representative CDC/Socrata pipeline.

### Unit tests

- Verify connector parsing for supported resource types, pagination, deterministic ordering, watermarks/cursors, retry classification, and redaction.
- Verify artifact hashing, manifest generation, duplicate-artifact handling, and RAW provenance-column population.
- Verify schema-diff classification and all configured quality-rule calculations.
- Verify that numeric zero, null, unknown, suppressed, and not-reported values remain distinct through RAW, STAGING, CONFORMED, and consumer outputs.

### Integration tests

- Test catalog registration through resource classification, access-profile selection, sample/schema capture, artifact landing, RAW load, quality gate, approval, STAGING transformation, CONFORMED transformation, and an ANALYTICS consumer.
- Test a multi-page API extraction and assert that every page is recorded in deterministic request sequence and that retrieved/landed/loaded counts reconcile.
- Test direct-file ingestion with an immutable raw artifact and checksum.
- Test a retryable failure (such as HTTP 429/5xx) and a non-retryable failure (such as HTTP 403), confirming that both are retained with correct status and redacted diagnostics.
- Test a schema, methodology, case-definition, license, and geography/time-semantic change, confirming that each produces a change event and blocks promotion pending a recorded review decision.

### Security and governance tests

- Scan request records, logs, error messages, and `VARIANT` fields to confirm that credentials, API keys, OAuth tokens, and prohibited sensitive payloads are absent.
- Verify role grants, classification tags, masking/row-access policies, and controlled-data boundary behavior.
- Verify that an output can be traced to its catalog resource, access profile, source version, artifact checksum, retrieval time, schema/document snapshot, transformation run, and caveat.
- Reconcile custom lineage edges with Snowflake-native object dependencies and access history for the reference pipeline.

### Acceptance test exit criteria

The pipeline implementation is ready for production consideration only when all required tests pass, the representative source is traceable end to end, failed/partial runs are retained rather than hidden, material changes are gated by review, secrets are absent from evidence records, and downstream outputs preserve required public-health semantics.
