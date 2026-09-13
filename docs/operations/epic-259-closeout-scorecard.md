# Epic #259 closeout scorecard

Parent: [Pipeline Simplification Phase 2](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/259).

This scorecard records the before/after supported-path count and the evidence
required before stories are marked done. Production status is intentionally
separate from local tests and CI.

| Measure | Before Phase 2 | After implementation | Evidence |
|---|---:|---:|---|
| Generic tabular sources on the shared orchestrator | 2 fixture-oriented proofs | 3 definitions (`x5j9`, `qtbi`, tick fixture) | `config/sources`, adapter/orchestrator tests |
| Routine live DEV Socrata paths | 0 end-to-end | 2 (`x5j9`, `qtbi`) | DEV run ID, V068 checkpoints, generic table counts |
| Routine live DEV HTTP/XLSX paths | 0; restricted envelope only | 0; remains Tier D | ADR 0023, Tier B/C rejection test |
| Supported x5j9 source-specific happy-path workflows | 2 | 0 | Deprecated workflows fail closed; generic workflow proof |
| Generic storage/load boundary | Source-specific RAW/COPY paths | 1 V069 generic boundary | Migration ledger and runtime SQL/effect tests |
| Manual technical stage unlocks for routine public DEV | Present in legacy design | 0 | Tier B run and durable resume evidence |
| Source-specific orchestration roles added | N/A | 0 | V069 grants only pipeline runtime |
| Fresh-process resume | In-memory payload dependency | File/Snowflake payload/checkpoint persistence | Resume test plus DEV run recovery |

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
- [ ] Local quality gates pass on the release commit.
- [ ] DEV migration and bounded live run complete on the release digest.
- [ ] The exact DEV digest is promoted through the protected PROD workflow.
- [ ] PROD job image digests, migration ledger, and runtime health are verified.

The final four checks are release evidence, not claims satisfied by a green
unit-test suite.
