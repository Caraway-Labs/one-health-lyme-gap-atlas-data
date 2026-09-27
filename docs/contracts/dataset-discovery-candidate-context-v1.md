# Dataset Discovery candidate context v1

Owner: Atlas data platform. Consumer: standalone Dataset Discovery application.
Status: draft; V112 is not applied and runtime SELECT grants require the ADR 0041
owner/security decision.

`DATASET_DISCOVERY.V_CANDIDATE_PRIOR_ASSESSMENT` returns at most one prior
governed assessment for a canonical candidate and discovery run. It uses the
latest assessment whose `assessed_at` is no later than the retained discovery
observation. The projection contains only the assessment ID, status, and time.
It does not expose quality scores, a source approval decision, limitations text,
or rights clearance. Missing rows mean unknown, not rejected.

`DATASET_DISCOVERY.V_CANDIDATE_ARTIFACT_METADATA` returns the exact artifact
ID, type, media type, byte count, SHA-256, retention class, and creation time
linked to each retained catalog observation. It excludes `artifact_uri`, raw
bytes, request endpoints, and payloads. Its SHA-256 is a retained artifact
content checksum, not the catalog metadata checksum. An application query must
filter by discovery run plus canonical resource/dataset/resource IDs, order by
observation ID and artifact ID, and use a reviewed row/byte limit. These views
do not authorize artifact fetching, source approval, or ingestion.

The assessment view is contextual governance history. Dataset Discovery must
never map its `assessment_status` to recommendation priority or reuse
`APPROVED / CONDITIONAL / REJECTED` as a candidate classification. The runtime
role may receive only reviewed SELECT on these projections after ADR 0041;
it receives no `GOVERNANCE` or `RAW_ARTIFACTS` table grant. Use the protected
migration ledger to apply V112. Rollback removes future runtime grants and
uses a forward view migration; existing recommendation assertions stay immutable.
