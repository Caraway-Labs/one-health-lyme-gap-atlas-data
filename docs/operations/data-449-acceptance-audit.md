# Data #449 DEV acceptance audit (2026-09-28)

Scope: Data #449 persistence and runtime authority in DEV. PROD remains untouched. This matrix distinguishes applied SQL, fixture tests, and observed DEV behavior. ADR 0041 remains Proposed in the repository and needs an explicit owner/security disposition.

| Criterion | Status | Evidence | Remaining action |
| --- | --- | --- | --- |
| Environment-local schema, tables, bounded views and receipts | PARTIALLY PROVEN | DEV ledger has V106–V113 and V114–V116, V119–V122 receipts; migration SQL defines the objects. Data #449 issue comments record earlier bounded runtime reads. | Verify relevant live object/view contents and migration checksum against current source. |
| Append-only recommendation versions and review history | PARTIALLY PROVEN | V106/V109 definitions and fixture contract tests; one recommendation receipt visible to DEV runtime at audit time. | Prove separate-run versions and review history with live identities. Human review is blocked by ADR 0041. |
| Run and candidate idempotency, terminal finalization | PROVEN | Data #449 DEV comment (2026-09-27) records independent-session same-key run and concurrent candidate outcome, exact/conflicting replay, lost ACK, terminal receipt; later real SHADOW run receipts. | Preserve receipts in final audit; no repeat needed. |
| Atomic recommendation, evidence, proposal, replay and lost ACK | PARTIALLY PROVEN | Two DEV fixture runs through the standalone typed adapter returned one recommendation version, exact evidence ID, one inactive proposal ID, and final status. Concurrent calls returned equal receipts; a later keyed read recovered the receipt, exact replay matched, and changed-content replay failed. | A controlled failure after the first bundle insert is still needed for rollback proof. |
| Recommendation rollback and concurrent serialization | PARTIALLY PROVEN | Independent runtime sessions raced the same operation key in each of two DEV test runs; both returned the same receipt and a keyed read found one version. V108 holds the serialization-row update inside its transaction. | Exercise a fault during the multi-object insert path and verify no recommendation/evidence/proposal residue. Recheck contention under that fault. |
| Canonical catalog/evidence links and observed versus inference/unknown | PARTIALLY PROVEN | The DEV fixture read an actual completed catalog snapshot and retained title/observation, then persisted its exact evidence reference. The typed assertion had separate observed, inference and unknown fields. | A genuine application-generated recommendation, not this labeled acceptance assertion, remains needed for application acceptance. |
| Secret exclusion and retention/redaction/query limits | PARTIALLY PROVEN | V106 bounded views and request allowlist; Dataset Discovery specs and tests prohibit raw payloads. | Review live projection/retention settings and document residual limits. |
| Runtime least privilege | PROVEN | Data #449 DEV comment records executable denials. On 2026-09-28 the runtime user/role/database/warehouse were reverified; `SHOW GRANTS TO/OF ROLE` showed only four write-procedure USAGE grants, bounded view SELECT, schema/database/warehouse USAGE, no inherited role, and service-user assignment only. A direct GOVERNANCE base-table read failed authorization. | Revalidate in PROD only after separate promotion approval. |
| Human reviewer attribution and review write authority | BLOCKED BY ADR 0041 | ADR 0041 remains Proposed; V109/V114 code and DEV bootstrap documentation do not constitute owner/security acceptance. | Decide role assignment and WRITE_OWNER READ SESSION or reviewed alternative; then run human principal test. |
| Handoff status and exactly-once governed onboarding | BLOCKED BY ADR 0041 | V110/V113 and draft handoff contract exist. Data #450 owns real attributable ACCEPTED_FOR_INVESTIGATION to governed handoff. | Decide review identity, then complete Data #450; do not count migration existence as end-to-end proof. |
| Migration ledger, recovery and role model | PARTIALLY PROVEN | Data #454 closed with V103 recovery; DEV ledger query on 2026-09-28 shows V106–V117 and V119–V122, with no V118 receipt. V106–V113 remain unpromoted. | Reconcile current-source checksum and precise role decision before PROD readiness. |
| Standalone typed adapter round trip | PARTIALLY PROVEN | `scripts/verify_dataset_discovery_recommendation_dev.py` used the actual `SnowflakeRecommendationRepository` with a DEV runtime PAT. Two labeled test runs reached V107/V108, recovered V106 receipts and finalized; both stored one logical version. | A genuine non-fixture agent recommendation remains application #9/#11 work. |

Primary prior evidence: [Data #449](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/449), [Data #454](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/454), [Dataset Discovery #9](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-dataset-discovery/issues/9). The matrix was built before the new probe and updated only after observing its DEV results.

## New DEV receipt evidence

The probe ran three times on 2026-09-28, with the last run using the final script text. It used a completed DEV discovery snapshot and exact retained observation field. Its `data449-acceptance-*` run IDs, zero-filled code/config fingerprints, and `DEV_ACCEPTANCE_TEST_ONLY` proposal scope explicitly mark test assertions. They are not a real agent suitability finding and do not change active search configuration, authoritative source approval, ingestion, or publication.

| Run | Version | Result |
| --- | --- | --- |
| `data449-acceptance-d89ec13e873b4765b8f4a7966a86ef93` | `a89ecf1201b98819f16ce45bf6083ccdd9f2c628b8857500e6e15ca3e9e73a11` | Two independent concurrent sessions returned equal receipts; exact replay, conflicting replay denial, lost-ACK keyed read, one receipt, and terminal `SUCCEEDED_WITH_RECOMMENDATIONS`. |
| `data449-acceptance-6f6047cd3ba3463b886d720eec911caa` | `e4d6a55f4a1c822901d48b9d311c583f7e78f951d8569f0229e76a90b0b4c9e2` | Same checks, plus exact evidence and one inactive proposal ID assertions. |
| `data449-acceptance-8da130093e1a4a1a972edaf0f50d91d3` | `8d9e1d588ee07a75805a0ccfcf514ea4d56505df1d592d574593b7d05338e09d` | Final script: same checks passed with one logical receipt and terminal `SUCCEEDED_WITH_RECOMMENDATIONS`. |

The replay test discards the first returned object for its recovery check and reads by operation key. Conflict changes the relationship basis and recomputes a valid assertion hash; the procedure returns `CONFLICTING_OPERATION_REPLAY`. The test does **not** prove a mid-bundle rollback: V108 validates all evidence and proposal inputs before inserting the first row, so a malformed request fails too early. A safe DEV-only fault mechanism or a reviewed forward migration is required to inject a failure after insertion and check all three tables. Do not describe this gap as proven from the `ROLLBACK` statement alone.

## ADR 0041 owner/security decision packet

The repository ADR remains **Proposed**. DEV roles and grants exist, and DEV bootstrap documentation calls the architecture approved, but that operational fact does not resolve the recorded ADR status or authorize PROD replication. The smallest formal decision is:

1. **Three separate roles:** approve or reject `DATASET_DISCOVERY_RUNTIME` (bounded view SELECT and four procedure USAGE grants), individually assigned `DATASET_DISCOVERY_REVIEWER` (pending/detail/history SELECT plus review/handoff procedure USAGE), and non-login `DATASET_DISCOVERY_WRITE_OWNER` (only procedure dependencies and ownership). This preserves the service/human/DDL separation; it adds three roles per environment and an ownership hierarchy edge to administer.
2. **Role administration:** name the account-level actor allowed to create the roles and assign runtime and individual reviewer users; allow the protected migration deployer to assume WRITE_OWNER only to create/replace the reviewed procedures. No broad `MANAGE GRANTS` or inheritance by runtime/reviewer.
3. **Caller attribution:** approve or reject account `READ SESSION` for WRITE_OWNER only. This permits an owner-rights V109 procedure to derive the Snowflake human principal without reviewer table DML, but an account-level privilege warrants a narrow owner/security review and an explicit denial test for service/shared principals.
4. **If rejected:** select a separately reviewed attribution mechanism (for example a trusted identity-binding service with verifiable signed principal context), its operator and audit contract, and a replacement V109/V110 procedure design. Do not use a client-supplied reviewer string or `CURRENT_USER()` inside owner rights as caller proof. The alternative delays #449 review-attribution closure and #450 handoff proof.

Recommendation: approve the three-role separation and narrowly scoped READ SESSION for the non-login procedure owner, with individually authenticated reviewer assignment and live `USER_PERSON`/service denial tests. This matches the existing owner-rights architecture while keeping table DML and source approval away from runtime/reviewer. Security may choose the alternative, but it requires a new reviewed identity contract before review writes can count.

## Closure and migration classification

**Data #449 cannot close yet.** The exact blocking technical criterion is mid-bundle rollback; the live fixture does not prove a genuine agent recommendation. Its issue text also explicitly requires attributable review history, and that part is `BLOCKED BY ADR 0041` unless the owner narrows #449 to runtime persistence and assigns the human review criterion to #450/#9. Such a scope change must be recorded, not inferred. Data #450 can prepare its data-owned handoff tests now, but the real recommendation → attributable `ACCEPTED_FOR_INVESTIGATION` → exactly-once handoff proof waits for the reviewed human identity boundary. Handoff alone must not approve or ingest a source.

| Migration | DEV behavior | Governance/PROD readiness |
| --- | --- | --- |
| V106 | Applied; schema, bounded views and receipts exercised. | ADR/role decision unresolved; not PROD-ready. |
| V107 | Applied; create/finalize path and prior candidate-outcome evidence exist. | DEV runtime proven; full release review pending; not PROD-ready. |
| V108 | Applied; two concurrent typed-adapter fixture commits/replays passed. | Mid-bundle rollback and genuine application output pending; not PROD-ready. |
| V109 | Applied definition; no accepted human review proved here. | BLOCKED BY ADR 0041 caller-attribution decision; not PROD-ready. |
| V110 | Applied definition; no real accepted handoff proved. | Data #450 and ADR 0041 gate; not PROD-ready. |
| V111 | Applied identity-link definition. | Shared promotion gate remains; not PROD-ready. |
| V112 | Applied candidate-context definition, later DEV projection repair. | Shared promotion gate and checksum/source review remain; not PROD-ready. |
| V113 | Applied handoff snapshot validation definition. | Data #450 live handoff and shared promotion gate remain; not PROD-ready. |

V114–V122 are DEV-only history/repairs, not automatic PROD permissions. Current DEV ledger query found no V118 entry; that absence must be reconciled against the intended release plan rather than described as successful application. No PROD mutation occurred.

Local gates after `uv sync --extra dev`: `uv run ruff check .` passed, `uv run ruff format --check .` passed, `uv run mypy src` passed (83 files), `uv run pytest -q` passed (1,153 tests), and `git diff --check` passed. No migration or container asset changed; dbt/container deployment gates are deferred to the protected promotion workflow.
