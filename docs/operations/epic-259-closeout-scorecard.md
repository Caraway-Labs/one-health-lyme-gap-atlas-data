# Epic #259 closeout scorecard

Parent: [Pipeline Simplification Phase 2](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/259).

This scorecard records the before/after supported-path count and the evidence
required before stories are marked done. Production status is intentionally
separate from local tests and CI.

| Measure | Before Phase 2 | After implementation | Evidence |
|---|---:|---:|---|
| Generic tabular sources on the shared orchestrator | 2 fixture-oriented proofs | 3 definitions (`x5j9`, `qtbi`, tick fixture) | `config/sources`, adapter/orchestrator tests |
| Routine live DEV Socrata paths | 0 end-to-end | 1 verified (`x5j9`); `qtbi` has the generic definition/path but no live run in this release | DEV run ID, V068 checkpoints, V069 generic table counts |
| Routine live DEV HTTP/XLSX paths | 0; restricted envelope only | 0; remains Tier D | ADR 0023, Tier B/C rejection test |
| Supported x5j9 source-specific happy-path workflows | 2 | 0 | Deprecated workflows fail closed; generic workflow proof |
| Generic storage/load boundary | Source-specific RAW/COPY paths | 1 V069 generic row/publication boundary plus V070 durable payload/normalized persistence | Migration ledger and runtime SQL/effect tests |
| Manual technical stage unlocks for routine public DEV | Present in legacy design | 0 | Tier B run and durable resume evidence |
| Source-specific orchestration roles added | N/A | 0 | V069 grants only pipeline runtime |
| Fresh-process resume | In-memory payload dependency | Snowflake payload/normalized/checkpoint persistence with retained-artifact recovery | Resume test plus DEV run recovery |

## Acceptance evidence

- [x] #253 inventory and explicit dispositions recorded.
- [x] #254 qtbi definition, normalization, and generic orchestration path added.
- [x] #255 generic workflow executes without forced dry-run; x5j9 legacy paths
      fail closed; generic load is idempotent and lineage-bearing.
- [x] #256 tick remains a permanent, bounded Tier D exception with revisit and
      exit criteria.
- [x] #257 durable literature stages and append-only recovery boundary retained;
      no manual technical unlock added.
- [x] #258 this scorecard records path counts and evidence boundaries.
- [x] The executable runtime release commit `098c5ca` passed local and hosted
      quality gates (Quality run
      [34919022683](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/34919022683)).
      The final scorecard-only follow-up commit `f7407de` also passed hosted
      Quality and DEV migration verification.
- [x] DEV V070 migration and bounded live x5j9 run complete for the executable
      runtime release: migration run
      [34919495572](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/34919495572);
      ingestion run
      [34919615186](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/34919615186).
      The final scorecard follow-up was revalidated by
      [34920925549](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/34920925549).
- [x] The exact DEV digest `sha256:53a5b635b420e8530d4c07b46ef667b063603badd4ac355748aa2c4add904ecc`
      is promoted through protected PROD workflow
      [34919924604](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/34919924604).
- [x] PROD job image digests, migration ledger, and runtime grants are verified
      read-only: V069 and V070 each occur once; V070 records commit `098c5ca`;
      all six scheduled jobs use the promoted digest.

The live proof is intentionally bounded to DEV x5j9. No PROD source ingestion,
Alpha POC replacement, API cutover, or Tier D tick-workbook promotion is implied.

The final four checks are release evidence, not claims satisfied by a green
unit-test suite.
