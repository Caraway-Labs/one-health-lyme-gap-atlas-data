# KG #15 current-path completion audit

Audit boundary: 2026-10-01, DATA main `f5c8048131c23214c21a399296392ec9f704daf3`.
Implementation owner: DATA. Release and production execution remain with the
coordinating owner. This is a repository/evidence audit with a bounded read-only
classification metadata check for PR541 rereview. No extraction, provider call,
grant, topology update, graph identity
rewrite, or receipt rewrite was performed by this audit.

## Completed work to reuse

- [DATA #528 final acceptance](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/528#issuecomment-5931730911)
  closes the observability work: durable sanitized diagnostics, actual collector
  receipt, prospective discovery scope, stage status and receipt-to-build joins.
- [PR #539](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/539)
  provides batched atomic corpus replacement. The owner's completed workflow
  [36862412515](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/36862412515)
  records build `5120d0df-8dbb-435f-b989-6f91beb4a990`, discovery scope
  `c17767c6-b70f-441d-b709-9cb647834715`, 100 papers and 4,018 units with exact
  graph receipt joins. The owner verified 100 graph papers and 222 passages.
- Historical failed build `765bc554-df72-4f0a-833a-1d9a9beb1f75` remains failed;
  the completed build is separate. Do not reclassify historical partial output as
  a completed receipt or repeat the already repaired writer.

## Acceptance mapping and remaining limits

| KG #15 criterion | Current evidence / remaining acceptance requirement |
| --- | --- |
| Aggregate preflight before mutation | `literature_preflight(operation="all")` aggregates runtime stage blockers before paper claim. The host-secret follow-up aggregates missing operation and inherited runtime credentials before App update; its report explicitly does not claim runtime readiness. Other host image/topology guards remain fail-fast, and private connectivity is checked after temporary app/VPC deployment. Full single-result-before-topology-mutation acceptance remains open. |
| DATA #517 before claim | Actual runtime identity, columns, inherited write grants and diagnostics capabilities are checked. This patch additionally checks required classification tokens and qualified budget procedure object names; it makes no grant changes. Procedure overload compatibility and underlying owner dependencies are not exercised by a non-mutating budget call. |
| Missing secrets together by stage | Runtime preflight aggregates names by stage. The host-secret follow-up reports all known required operation and inherited credential omissions together, with stage/owner/retry/next-action context, and blocks spec generation and both deployment/restoration updates. Offline real-workflow execution verifies this boundary; no new production run is claimed. |
| Image/workflow/topology drift | Protected workflow verifies immutable source image, DEV/PROD digest agreement and reviewed six-job topology. CLI identity checks verify field shape/presence; they alone do not compare deployed identity to an expected release. |
| Private Neo4j connectivity | Existing protected preflight checks Bolt connectivity in the temporary reviewed VPC. It does not prove connectivity before that app-level mutation. |
| Canary through serving and corpus before batch | Completed one-paper and final corpus evidence exists; final batch rebuild is not a pre-batch canary. The strict same-group fresh canary criterion is authorized. The first [group gate slice](kg15-group-gate.md) fences existing group attempts and always blocks continuation until authoritative receipt/freshness and actual serving visibility checks are implemented. No production proof or completion claim. |
| 10-25 group durable stop/resume | An explicit group manifest binds claims to exactly 10–25 distinct, steward-approved PMIDs in the authoritative discovery inventory, with image/configuration identity and append-only attempt context. Approval/scope drift blocks before claim. This initial seam does not expose workflow activation, implement group continuation/recovery or complete before/after reconciliation. Existing one-paper operations are not proof of group acceptance. |
| Counts reconcile / typed failures | DATA528 status reconstructs stage evidence and exact failures. Historical attempts are `legacy_unclassified` and unlinked builds `not_attributed`; overlapping stage counts are not a mutually exclusive inventory funnel. Exact batch inventory reconciliation remains to be demonstrated. |
| Injected transient retry/idempotency | Existing discovery request retries, worker failure tests, publication replacement tests and atomic corpus rollback tests should be reused. Provider execution remains explicitly one request per invocation, with later governed retries. No blanket provider backoff/jitter acceptance claim is made. |
| Terminal fail-closed | Existing OA/license/identity checks, approval and provider rejection classification preserve terminal behavior and the confirmed-execution failure ceiling. No controls are relaxed by this patch. |
| One primary runbook | [Bounded production operations](prod-literature-one-shot.md) remains the primary entry point, with `literature-status` as the read-only status path. The temporary topology choice and alternatives still need owner review under KG15 section C. |
| Governance / no new platform | This patch only strengthens read-only contract checks and adds regressions. No new service, migration, queue, timer, grant or credential. |
| DATA495 hardened-path execution link | DATA528 final evidence supplies authentic current receipt/build links. DATA495 final completion and KG13 serving QA remain owned by the coordinating production task. |

## Citation identity risk

[KG15 comment 5930279987](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-knowledge-graph/issues/15#issuecomment-5930279987)
records two reused passage-ID groups covering ten passages. API grounding first
uses an ID-only dictionary, then exact PMID and literal quote checks. The recorded
offline replay rejected the wrong-source PMID. An accepted wrong-source answer
has not been demonstrated. Ambiguous lookup can reject valid citations; it must
not be described as proven accepted misattribution.

The DATA publisher creates paper-owned passages without a cross-paper identity
collision check. Addressing publication-time identity validation and API lookup
requires a separately reviewed plan that preserves current IDs and receipts.
Do not install uniqueness constraints or rewrite historical IDs as an incidental
preflight repair. KG13 QA should report this limitation explicitly.

## Narrow change and release boundary

This patch rejects a runtime grant on a different database/schema or a similarly
named budget procedure. Its PMC classification check is scoped to the target
table and recognizes only a supported positive `CLASSIFICATION IN (...)`
expression containing both exact lowercase worker values. Missing constraints,
`NOT IN`, uppercase-only literals and unknown expression forms block readiness.
It does not evaluate arbitrary SQL or prove every possible classification contract.
It reuses `missing_capabilities` and the existing typed
`runtime_contract` blocker path. The checks use metadata reads only and execute
before claim; no budget reservation is invoked.

On 2026-10-01, the existing `ATLAS_PROD_RUNTIME_AUDIT` connection first verified
role `OH_LYME_PROD_RUNTIME`, database `ONE_HEALTH_LYME_GAP_ATLAS_PROD` and warehouse
`OH_LYME_PROD_INGEST_XS_WH`. A bounded SELECT on `INFORMATION_SCHEMA.CHECK_CONSTRAINTS`
returned schema `KNOWLEDGE_GRAPH`, name `CK_PMC_ATTEMPT_CLASSIFICATION`, table
`EXTRACTION_ATTEMPT_CLASSIFICATIONS`, and this exact structural `CHECK_CLAUSE`:

```sql
classification IN (
      'provider_rejected_pre_inference',
      'contract_remediation_reopen'
    )
```

That live serialization is retained as a fixture in both the full capability
check and clause-recognition regressions. Only structural metadata was read;
no secret or paper content was retrieved. The PR branch was then reconciled onto
main `5271fe9834ffbec3e311156da256c9b56b53f3ac` for final rereview; V135 was unchanged.

Independent review, required quality gates and reconciliation against fresh main
precede owner-coordinated release. A blocked production check requires investigation
of the installed contract through existing authorized connections; it does not
authorize broader grants, migration replay or bypass. KG15 remains open until its
remaining criteria are proved or explicitly scoped by the product owner.
