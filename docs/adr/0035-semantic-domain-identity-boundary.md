# 0035: Semantic domain identity boundary

Status: Proposed
Date: 2026-09-24
Decision owner: Atlas product/data stewardship and engineering

## Context

V071/V072 already deliver a fixed county semantic release; V100–V102 preserve separate DEV-only derived results. Forcing native site/event or source-only evidence into the fixed county release would change published meaning and counts. Story #190 needs reusable identities without another persistence system.

## Decision

Adopt `atlas-semantic-domain-v1` as a storage-neutral, versioned definition and validation contract. Reuse source/dataset/indicator/measure identities where their meaning matches, distinguish scientific observation key from immutable revision and release membership, and retain existing physical rows/IDs. Compose the #157–#159 quality, eligibility, limitation, and evidence contracts by reference. No new table, registry service, release pointer, or public view is introduced.

## Consequences

Downstream adapters can describe county, site/event, derived, and source-only shapes without migrating history. The current county hierarchy's `county_geometry` versus physical `geometry` observation ID mismatch remains historical; #192 must map it explicitly rather than silently rewrite it. Cross-version equivalence, broader metadata, lineage edges, and consumer projections remain #191–#195 work. No public health interpretation or source authorization changes.

## Alternatives considered

- Extend V071 with all site/event and derived columns: rejected because current fixed release and pointer would acquire incompatible meaning.
- Create one parallel semantic observation store now: rejected because existing canonical and derived stores already own immutable rows; persistence need is unproven.
- Keep only prose: rejected because identity, value-state, and compatibility rules require executable checks.

## Acceptance criteria

The v1 validator rejects incompatible meaning, grain, time, value state, provenance, and duplicate/revision collisions. Fixtures cover current county shapes and representative native and derived shapes. Historical migrations and pointer remain unchanged.

## Rollout, observability, and rollback

Contract-only change; local tests and hosted Quality are the gates. No database rollout is required. Reverting the contract commit leaves all historical database records unchanged.

## Links to affected contracts and tests

`docs/contracts/semantic-domain/atlas-semantic-domain-v1.md`; `src/lyme_gap_atlas_data/semantic_domain.py`; `tests/test_semantic_domain.py`.
