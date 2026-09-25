# Story #194 proposed completion evidence

Baseline: data `origin/main` `b1aecd64627e13c0af1e1db4d4d6a4a502f2dca5`, API `3428ebf737ce9e4fd890181c5a49ba6c8a693bab`, Web `bfe5c968117efc999596673d5d7c74f346636955`. The read-only audit and decision matrix preceded code in commit `d493f1d`.

| Acceptance criterion | Proposed merged-state evidence | Limit |
| --- | --- | --- |
| INTERNAL / CONSUMER_SAFE / PUBLIC | `atlas-semantic-consumer-v1.md` field matrix and `project_consumer` visibility/review gates | Existing API remains the only PUBLIC interface |
| Stable, meaningful machine representation | #190–#193 validators composed before explicit projection; semantic, metadata, observation, lineage and release revisions pinned; deterministic JSON | Real authority snapshot must be supplied by caller |
| Map to actual models/views | Contract names current `PRESENTATION` views, fixed county release, separate derived stores and deferred historical adapters | No new DB object or live service adapter |
| Coordinate API/OpenAPI/client | API #52 remains open and blocks #53/#55; no public contract change or generated-client refresh is applicable | API discovery remains separate backlog scope |
| Behavioral and adversarial tests | `test_semantic_consumer.py`: county/site/source-only, valid/unknown IDs, bounded filters/pages, states, unsafe values, restricted proof exclusion, reproducible revisions, internal derived exclusion | Synthetic fixtures, not live source approval |
| #158/#159 remain internal | Existing metadata validator requires internal derived visibility; projection repeats explicit denial | No public derived resource |
| Evidence separation | Local pytest/Ruff/mypy/dbt and hosted Quality are reported separately; no runtime claim | DEV, PROD and live API not exercised by this storage-neutral change |
| No MCP/public agent | No MCP or agent files changed | Separate approved scope required |

The frozen #195 county-release fixture and existing semantic-release/API-facing regression tests run in the full data suite. The data diff contains no migration, SQL, view, publication pointer, source acquisition, API, Web or generated OpenAPI file. A future #53/#55 API implementation must obtain #52's public resource/access decision and use the reviewed data projection, with its own OpenAPI and Web generation PRs.
