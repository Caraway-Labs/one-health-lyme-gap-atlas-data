# 0022: DEV public-source evidence envelope

Status: Accepted
Date: 2026-09-09
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

Workspace ADR 0005 assigns approved-source acquisition to the isolated
DigitalOcean runtime because that identity owns the DEV Snowflake and private
Spaces credentials. During evidence-only onboarding of the CDC county-status
workbook, two retained attempts proved that the CDC web front door returns HTTP
403 to the DigitalOcean egress even with browser-compatible headers. The same
pinned public URLs are reachable outside that egress. Repeating the unchanged
route would add failed evidence without improving the chance of success.

The candidate still requires first-party landing-page and workbook bytes,
checksums, retrieval provenance, schema validation, and source-semantic review.
Moving Snowflake or Spaces credentials into GitHub would violate the environment
boundary. Treating a local download as sufficient evidence would weaken
reproducibility and the protected execution trail.

## Decision

For this DEV-only evidence candidate, the manually dispatched GitHub workflow
may retrieve exactly the two pinned public CDC HTTPS resources. It enforces
redirect host, response status, media type, compressed byte limits, and SHA-256
checksums, then creates a versioned acquisition manifest containing the GitHub
run provenance and the exact active DEV base-image digest.

The workflow builds a short-lived private OCI evidence envelope `FROM` that
base digest. The overlay contains only the two public publisher files and their
manifest. A temporary non-routable DigitalOcean PRE_DEPLOY job inherits the
existing encrypted DEV runtime configuration and runs the envelope by immutable
digest. The runtime independently verifies the manifest, base and envelope
digests, repository/run provenance, URLs, status, media types, byte counts, and
payload checksums before applying the existing landing-page, XLSX, schema,
ordering, and semantic checks.

Only the DigitalOcean runtime can write the unchanged files and manifest to
private Spaces and append Snowflake evidence. GitHub receives no Snowflake or
Spaces credential. The workflow restores the exact prior DEV app specification
and removes the temporary registry tag on success or failure. The untagged OCI
content is subject to the private registry's governed retention and garbage
collection; the authoritative retained copies and manifest are the checksummed
Spaces artifacts.

This is a bounded onboarding exception, not a general connector or a scheduled
PROD acquisition topology. Any recurring or PROD use requires a separate ADR,
threat review, operational owner, and approval.

## Consequences

The public bytes cross a GitHub runner, but secrets and write authority do not.
The acquisition route is split across two actors. The manifest records the
GitHub retrieval identity and base-image digest; retained runtime metadata adds
the envelope digest without creating a circular image checksum. Runtime
verification fails closed before candidate creation if any byte or provenance
field differs.

The temporary tag is discoverable in the private registry during the run and is
deleted afterward. Deleting a tag does not guarantee immediate physical layer
deletion, so registry retention remains an operational control. No workflow
artifact, log statement, or public image publishes source payload bytes.

## Alternatives considered

- Repeating DigitalOcean egress was rejected after two equivalent HTTP 403
  failures.
- Copying DEV Snowflake/Spaces credentials to GitHub was rejected because it
  broadens the trusted secret boundary.
- Running locally was rejected because it lacks protected, reproducible runner
  and deployment evidence.
- Introducing a proxy or permanent fetch service was rejected as excessive new
  infrastructure for one bounded evidence candidate.
- Skipping the landing page was rejected because its terms and status semantics
  are required steward evidence.

## Acceptance criteria

- The workflow fetches only the two pinned first-party CDC HTTPS URLs and fails
  on a non-200 response, off-host redirect, unexpected media type, or byte-bound
  violation.
- The overlay is based on the exact digest already active in DEV and is deployed
  by immutable envelope digest.
- The runtime recomputes every payload checksum and rejects altered manifest,
  route, GitHub provenance, base digest, envelope digest, or resource identity.
- The landing page, workbook, and acquisition manifest are retained as immutable
  private artifacts before a pending candidate is created.
- The prior DEV topology is restored and the temporary tag is removed on both
  success and failure; cleanup failure makes the workflow fail.
- No PROD, Alpha POC, RAW, dbt, approval, or scheduled-workload mutation occurs.

## Rollout, observability, and rollback

Merge only after the Python, workflow-policy, dbt-parse, and container gates
pass. Deploy the reviewed base image to DEV, then dispatch the evidence workflow
with that exact active digest. Correlate the GitHub run, DigitalOcean deployment,
Snowflake ingestion run/requests, and manifest digests. Confirm topology and tag
cleanup before steward review.

Rollback is topology restoration and temporary-tag deletion; append-only
failure and artifact evidence is retained. Do not delete a failed ingestion run
or overwrite a candidate. A failed restoration stops further pipeline work.

## Links to affected contracts and tests

- `docs/contracts/catalog-to-snowflake/requirements.md` FR-3.6
- `docs/contracts/catalog-to-snowflake/implementation-decisions.md`
- `docs/operations/cdc-tick-surveillance-dev-onboarding.md`
- `src/lyme_gap_atlas_data/tick_surveillance.py`
- `.github/workflows/capture-dev-cdc-tick-surveillance.yml`
- `tests/test_tick_surveillance.py`
