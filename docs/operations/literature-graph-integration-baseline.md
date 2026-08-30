# Literature/graph integration baseline

Date: 2026-08-30
Project item: `01 — Establish a clean integration baseline for the literature/graph work`

## Scope and clean base

This record inventories and plans only. No dirty-worktree file was copied,
staged, reset, cleaned, or changed. It does not authorize migrations,
deployment, production promotion, feature enablement, or a merge.

| Repository | Resolved `origin/main` |
| --- | --- |
| Data | `046f44f6db93358568d5d137c1298a8b8a68aa94` |
| Knowledge Graph | `96ec50ef88a52d06b2589bab2afd072c7f755886` |
| API | `bed9420f70d7c98e5194a65d1fd83739d232f627` |
| Shared Python | `c6f28b3ca47fef8cf39c6508bc5277f1a7f57c14` |
| Web | `a4bdf0c555d7ee2546ecc96478259641ce728b21` |

The clean Data integration worktree is
`C:\\codex_programming\\lyme-literature-graph-integration`, on
`codex/literature-graph-integration-baseline`, tracking `origin/main` at the
recorded Data commit.

## Complete dirty-path map

`S` = staged, `U` = unstaged, `N` = untracked. Assignments are to later
independently-reviewable project items; a path with two items must be split and
merged only once.

| Path | State | Assignment / disposition |
| --- | --- | --- |
| Data `.do/app.yaml` | S | 04, 05 — split DEV discovery and extraction schedules. |
| Data `.do/app.prod.yaml` | S | Exclude — production configuration needs separate explicit approval. |
| Data `.env.example` | S | 04, 05 — names only; never inspect/copy secrets. |
| Data `.github/workflows/promote-prod.yml` | S | Exclude — protected manual promotion only. |
| Data `README.md` | S | 02–05 — split with each implementation. |
| Data `docs/contracts/catalog-to-snowflake/streamlit-snowflake-approval-app-requirements.md` | U | 02 — redacted, human-review-bound console contract. |
| Data `docs/operations/knowledge-graph-live-acceptance.md` | N | 06 — DEV evidence and owner decision only. |
| Data `scripts/attach_app_vpc.ps1` | N | 05, 06 — private Neo4j connectivity; infrastructure approval required. |
| Data `scripts/provision_prod_runtime.py` | S | Exclude — not a DEV-only deliverable. |
| Data `migrations/V030__knowledge_graph_pipeline_grants.sql` | N | 03 — pipeline least privilege. |
| Data `migrations/V031__knowledge_graph_conversation_history.sql` | N | 03 — capability-token procedure/history boundary. |
| Data `migrations/V032__knowledge_graph_pmc_artifact_ledger.sql` | N | 03, 05 — ledger contract then extraction consumer. |
| Data `migrations/V033__pipeline_observability_views.sql` | N | 02 — read-only redacted views. |
| Data `src/lyme_gap_atlas_data/cli.py` | S+U | 04, 05; exclude root-span portions merged in #32. |
| Data `src/lyme_gap_atlas_data/extraction.py` | S | 04, 05 — retain bounded-worker responsibilities. |
| Data `src/lyme_gap_atlas_data/graph_extraction.py` | N | 05 — approved-paper, passage-backed graph publication. |
| Data `src/lyme_gap_atlas_data/pmc_graph.py` | S | 03, 05 — provenance and graph contribution compatibility. |
| Data `src/lyme_gap_atlas_data/pubmed_pipeline.py` | N | 04 — EFetch artifacts, normalization, review queue, limits. |
| Data `src/lyme_gap_atlas_data/settings.py` | S | 04, 05 — server-only configuration. |
| Data `src/lyme_gap_atlas_data/snowflake_extraction.py` | N | 03, 05 — ledger, lease, budget persistence. |
| Data `streamlit_approval/README.md` | U | 02 — operator documentation. |
| Data `streamlit_approval/streamlit_app.py` | U | 02 — read-only pages, filters, pagination, empty/error states. |
| Data `streamlit_approval/output/` | N | Exclude — generated output must not be committed. |
| Data `tests/test_cli_observability.py` | N | Exclude — already merged in #32/current main. |
| Data `tests/test_governed_pipeline.py` | S+U | 02, 03 — separate role/migration coverage from registration regressions. |
| Data `tests/test_graph_extraction.py` | N | 05 — negative, budget, idempotency cases. |
| Data `tests/test_pipeline_observability_console.py` | N | 02 — redaction/read-only/pagination tests. |
| Data `tests/test_pmc_graph.py` | S | 03, 05 — provenance/citation contract tests. |
| Data `tests/test_pubmed_pipeline.py` | N | 04 — artifact ordering, bounds, retries, rate limits. |
| Knowledge Graph `AGENTS.md` | N | Exclude — separate repository-guidance workstream. |
| Knowledge Graph `.github/` | N | 05, 06 — review contents under release approval. |
| Knowledge Graph `docs/diagrams/` | N | 03 — contract support, schema-owner review. |
| Knowledge Graph `docs/knowledge-graph-reference.md` | N | 03 — ontology/provenance compatibility. |
| Knowledge Graph `infra/Provision-Neo4j.ps1` | U | 05, 06 — private runtime/backup controls. |
| Knowledge Graph `infra/Configure-Neo4jRuntime.ps1` | N | 05, 06 — private runtime controls. |
| Knowledge Graph `infra/Install-Neo4jBackup.ps1` | N | 06 — backup/recovery setup. |
| Knowledge Graph `infra/Open-Neo4jDevTunnel.ps1` | N | 05, 06 — DEV operator access, never browser access. |
| Knowledge Graph `infra/configure-neo4j-runtime.sh` | N | 05, 06 — runtime counterpart. |
| Knowledge Graph `infra/install-neo4j-backup-runtime.sh` | N | 06 — backup runtime setup. |
| Knowledge Graph `infra/install-neo4j-backup.sh` | N | 06 — restore support. |
| Knowledge Graph `infra/backup-neo4j.sh` | U | 06 — recovery evidence. |
| Knowledge Graph `infra/configure-neo4j.sh` | U | 05, 06 — private runtime configuration. |
| Knowledge Graph `infra/README.md` | U | 05, 06 — operational documentation. |
| Knowledge Graph `tests/test_contracts.py` | U | 03, 05 — schema/publication contracts. |
| API `AGENTS.md` | N | Exclude — separate repository-guidance workstream. |
| API `src/lyme_gap_atlas_api/knowledge_chat.py` | U | 03, 06 — procedure/capability and safe disabled paths. |
| API `tests/test_api.py` | U | 03, 06 — capability, unavailable/no-evidence, safety tests. |
| Shared Python `AGENTS.md` | N | Exclude — separate repository-guidance workstream. |
| Shared Python `src/lyme_gap_atlas_shared/observability.py` | U | Exclude — separate observability item. |
| Shared Python `tests/test_observability_lifecycle.py` | N | Exclude — separate observability item. |
| Web `AGENTS.md` | S | Exclude — separate repository-guidance workstream. |
| Web `next-env.d.ts` | U | Exclude — generated/type-environment change. |
| Web `tests/api-mutator.test.ts` | N | 06 — browser/API negative boundary tests. |
| Web `tests/e2e/atlas.spec.ts` | S | Exclude — unrelated Atlas QA item. |

## Overlaps and required reconciliation

Data PR #28 is merged and overlaps dirty `.do/app.prod.yaml`,
`.github/workflows/promote-prod.yml`, `README.md`, `cli.py`, and
`test_governed_pipeline.py`; do not replace its registration fixes. PR #32 is
merged and overlaps `cli.py`; its observability test already exists on current
main. PRs #33–#37 are incorporated in this baseline and affect only
`.github/workflows/deploy-dev.yml`, which has no direct dirty-path overlap.

Before any port, compare against this baseline and split `cli.py` and
`test_governed_pipeline.py` hunks by ticket. V030–V032 belong to item 03 and
V033 to item 02; do not apply the migrations as one unreviewed batch.

## Verification

- Dirty worktrees were not reset, cleaned, checked out over, staged, or copied.
- The integration worktree began clean at `origin/main`.
- `git diff --check` passed on the clean base.
- A conflict-marker scan found no Git marker lines; existing CSS divider text
  in a status HTML file is not a conflict.
- No `.env`, key, generated Streamlit output, temporary worktree, or encrypted
  runtime configuration is assigned for commit.

Next: item 02 only, from this baseline, after contract/repository checks.
