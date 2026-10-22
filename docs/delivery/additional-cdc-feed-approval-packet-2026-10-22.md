# MMWR and Newsroom: bounded implementation and admission packet

The owner's eight-source selection and October 22 implementation direction are
the source-selection authority. This packet does not reopen that selection.
NIAID, WHO and Vital Signs remain deferred. PubMed's existing exact queries are
unchanged. NIH and PubMed HTTP403 responses are unresolved publisher access,
not requests for a verbal override or permission to bypass restrictions.

## Concrete proposed source and policy documents

| Source | Exact endpoint | Pending source document SHA256 |
| --- | --- | --- |
| cdc-mmwr | https://tools.cdc.gov/api/v2/resources/media/342778.rss | 638514d8085bd1c1eb79853ed27824b1b8a5cb4a207fa4514c60cf631b9b1aa1 |
| cdc-newsroom | https://tools.cdc.gov/api/v2/resources/media/132608.rss | 78b25be79247de406f29a5524c9ec29e76125e735de5f3c61a5b87b989ee8aee |

Documents and hash-bound native-policy proposals are in
`config/intelligence/proposed-five-feeds/`. Both sources remain `candidate` with
pending approval/trust review, no decision receipt, empty topics/geographies and
no inference. Their SourceDefinitions remain `artifact_policy: REVIEW_REQUIRED`.
Nothing in this PR makes a source eligible for live warehouse acquisition.

Owner decision `Sentinel_dafa6b0ae8108191b308b077e58b0f27`, October 22
01:17 UTC, approves the rest of this packet and changes metadata scope to
retain feed-provided descriptions/summaries and original category labels for
API availability. No UI previews or topic badges are authorized by that choice.

Each proposed native policy now permits eight paths: `feed/language`,
`feed/link`, `feed/title`, `item/link`, `item/pubDate`, `item/title`,
`item/description`, `item/category`. Description representation is complete
sanitized plain text, with explicit present/empty/not-provided states. It is
not generated or shortened; the existing excerpt remains withheld. Category
labels remain publisher labels, not validated/inferred scientific taxonomy.
No linked full article, asset/media bytes, media values or logos are acquired.
Native field inventory retains structure and withholding states for other
fields. Restricted raw RSS expires capture+30 days as previously proposed.

The eight-path policy is approved in scope but source documents remain
candidate/pending until reviewed final version/hash-bound runtime receipts and
the DEV capability/accounting preflight are complete. No production execution,
daily scheduling or native approval is inferred. Prior probes consumed none of
the new four sequential DEV capture/repoll runs. New approved runs used: **0**.
Live description values were not retained by earlier probes; content and size
qualification is still required during the approved bounded DEV workflow.
The unchanged 4096-character native field bound rejects oversize values, and
32,000,000 normalized bytes rejects the whole feed. Any incompatible real
value must be reported before expanding these bounds or changing semantics.

## Evidence and complete-feed limits

Current pinned-IP, verified-TLS GETs returned HTTP200 for both sources:

- MMWR: 2,343 entries, 1,951,668 bytes, no missing source links/dates;
  SHA256 `644d5479dc3c826214f277ded024dab8750bb1d03f934fc659758e72911dcdc5`.
- Newsroom: 1,844 entries, 1,416,838 bytes, no missing source links/dates;
  SHA256 `25637191064c0f340bd004ea76fe3cee62d20244beed2a9f921c3a1c8c525b8c`.

Value-free endpoint/size evidence is under
`docs/delivery/five-feed-evidence-2026-10-22/`. No XML is retained. Complete native
metadata alone measures 12,341,546 and 10,372,474 bytes respectively, exceeding
the old 10MB whole-write ceiling. A subsequent diagnostic attempt to create an
acquisition context stopped at `INTELLIGENCE_ACQUISITION_SOURCE_NOT_APPROVED`
for both pending documents. This is gate evidence, not successful normalized
or database delivery. Do not relabel those live bytes as a fixture or forge an
approved source to bypass it.

Proposed bounds: complete publisher document, maximum 3,000 entries, 2MiB raw,
30-second HTTPS deadline, one attempt, zero redirects, 32,000,000 normalized
bytes. Any excess rejects the entire capture; no newest-N slice, page omission
or chronology/link fabrication. This snapshot is publisher RSS coverage, not a
complete historical MMWR/Newsroom corpus or tick-borne relevance classification.

The extended DEV store writes at most 250 rows/900,000 canonical JSON bytes per
SQL batch inside the existing source/run transaction and write guard. All
artifact/context, native policy, immutable revision and capture checks remain.
Batch insert counts are checked. A later failure rolls back earlier batches;
there is no per-batch publication or commit. Existing 2,500-query/five-minute
invocation limits remain. The old pilot defaults remain unchanged, and expanded
PROD bounds are rejected by both composition and direct store construction.

## Approvals and execution order

1. **Code merge:** review the draft Data implementation, current quality and
   independent findings. Merge integrates code only. Actual current
   `.github/workflows/quality.yml` deploys DEV only for explicit
   `workflow_dispatch` with `deploy_dev=true`; main merge itself does not deploy.
   No production schedule, migration, source registration or grant is enabled.
2. **Native policy and registry receipt:** finalize the two owner-approved
   metadata/retention proposals and the stated complete-feed limits. A separately
   recorded actual decision must then finalize each `manual` source version and
   its reviewed receipt with the resulting checksum. Do not manufacture approval
   timestamps or reuse a pending-document checksum after changing its fields.
   Only the committed receipt may opt into `pass_bounds`; source YAML cannot.
3. **Finite DEV qualification:** owner-approved allowance is at most **US$5 total,
   four provider requests, four runs**, covering one complete capture and one
   unchanged repoll per named source, sequentially. This is an approved ceiling, not an estimate of actual charges. Reconcile private accounting,
   existing DEV runtime/retention capabilities and warehouse/resource headroom
   before dispatch; no borrowed allowance, new credentials or self-grants.
   Stop on the first admission, limit, lineage, storage, quality or accounting
   failure. Resume retained stages within the same limits; no automatic recapture.
4. **DEV acceptance:** prove both complete normalized checkpoints and atomic
   writes on Snowflake, including actual parameter/VARIANT size support, exact
   counts, immutable provenance, repoll/revision semantics and intended-reader
   retrieval. Local doubles and SQL parser checks are not engine proof.
5. **PROD admission/security:** only after DEV evidence, prepare a separate exact
   reviewed package extending current source-scoped raw cleanup for these two
   IDs while preserving the existing three sources. Targets include
   `ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT`
   (four VARCHAR arguments) and `INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V`.
   Native protected deployment, exact ownership/attestation handoff, source
   registration, capture and paid execution need their own concrete approval.
   No migration number, SQL security change, deletion plan or production run is
   reserved/dispatched here. Approval of this PR alone is insufficient.
6. **Refresh and consumer delivery:** proposed cadence is daily, using the
   existing canonical runner and idempotent capture semantics. Keep initial
   registry versions manual. Coordinate any later daily activation with the
   existing RSS owner after its independent run39697461617; do not alter that
   run, credential placement, or the six existing production jobs. Actual API
   service responses and rendered original links remain acceptance gates.

API PR279 separately repairs source catalog compatibility and requires its own
merge/deployment approval and real service-identity query proof. Web #822 remains
with Cursor. No source-level delivery or public-health claim follows from code
merge, a registry entry or green CI.
