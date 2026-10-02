# Surveillance evidence v1 — DATA429 review candidate

Status: **proposed, synthetic fixture only; scientific/steward approval pending**.
Executable boundary: `lyme_gap_atlas_data.surveillance_evidence`.
Contract version: `atlas-surveillance-evidence-v1`.

This companion envelope binds to an existing #190 observation key and immutable
revision. It retains geography, temporal semantics, taxon/pathogen/method strata,
source version/vintage and record anchor, and existing #157 quality/eligibility/
limitation references. It does not replace canonical observations or #188 lineage.
The existing consumer v1 JSON and its byte/revision behavior remain unchanged.
No source classifier, ingestion hook, dbt view, DDL or publication path is added.

## Vocabulary and value-state relationship

| State | Required meaning and evidence boundary |
| --- | --- |
| `established` | An explicit source definition supports establishment for the exact source, species/pathogen, grain and period. No universal numeric threshold is selected here. |
| `detected_below_establishment_criteria` | Source evidence explicitly supports detection and its relation to source establishment criteria. A positive test alone does not prove this relation. |
| `sampled_not_detected` | Qualifying sampling and non-detection must both be proved for the same scope. A generic zero, negative-like flag, or collection count is insufficient. |
| `no_qualifying_record` | Explicit source-scoped record status; never biological absence. Omission needs a separately reviewed complete-snapshot rule. |
| `unknown` | The source cannot support a stronger interpretation, criteria are incomplete, or geography remains unresolved. |

Evidence state is a separate interpretation dimension. It never rewrites existing
`ZERO`, `MISSING`, `UNKNOWN`, `SUPPRESSED`, `NOT_REPORTED`, `UNAVAILABLE`,
`NOT_DEFENSIBLE`, `NO_RECORDS` or `NO_COUNTY_LINKED_RECORD` value states. In
particular `NO_RECORDS` retains its literal, and unavailable/unobserved evidence
does not become sampled-negative. A stale explicit finding retains its original
period; no freshness threshold or current-status inference is introduced.

## Executable review boundary

All calls without literal boolean `fixture_mode=True` fail; truthy strings,
numbers and containers do not enable fixture mode. Fixture mode also requires a
validated reported observation with a `fixture-` source-version identity and an
explicit canonical tick taxon. Stronger states require an assertion bound to the
exact observation key/revision plus definition, eligibility-rule and criteria
references. Sampled-negative additionally requires explicit sampling/result
proof. Incomplete proof returns `unknown`; conflicting observation/revision
bindings fail. Source-only geography always abstains. Fixture attestations
demonstrate the interface only and do not verify real publisher evidence.

The internal content-addressed evidence revision includes source scope,
assertion and quality references; a source revision cannot reuse an old binding.
No mixed-source pooling or cross-grain equivalence is implemented. Site/event
observations retain `NOT_COUNTY_REPRESENTATIVE`, even with a contextual county
link. Passive submissions, host/person/pet samples and systematic host-seeking
samples must retain their existing method evidence; this code supplies no
missing method, identification confidence or encounter-location confidence.

## Consumer contract

`project_evidence_fixture` revalidates inputs and emits only the contract/version,
synthetic tier, state/reasons, semantic observation/revision IDs, evidence
revision, unchanged value state, limitations, and a bounded scope. The geography
projection excludes site/event private identifiers and physical mapping proofs.
Source records, artifacts, private rule/proof references and warehouse fields
are excluded. Consumers must bind both semantic IDs; the evidence revision does
not replace the semantic revision. This is a proposed companion payload, not a
change to `atlas-semantic-consumer-v1` or authorization for API #88/public use.

## Audit and primary references

Audited main `c5a23105719ac77f8abbca9b613b661654e22845`, #428/#429,
completed #430/#431, #156/#157/#188/#190/#191/#193/#195/#159, canonical tick
v1.2, semantic domain/source mappings/consumer boundaries, ADR 0035 and ADR
0027. No repository `.agents` directory was present. The external workspace
`TECHNOLOGY_AND_GOVERNANCE.md` and ADR 0005 were not located in this isolated
checkout; pipeline/source/deployment files are outside this change.

#430's methodology comparison is definition-scope metadata, while #431's
alignment is temporal eligibility. Neither authorizes DATA429 classification,
pooling, freshness or production scientific approval. Both remain independent.

[CDC blacklegged tick surveillance](https://www.cdc.gov/ticks/data-research/facts-stats/blacklegged-tick-surveillance.html)
(accessed 2026-10-02) documents cumulative establishment and warns that
non-established counties do not prove absence. Its definition is species/source
specific and is not generalized here.
[CDC pathogen surveillance](https://www.cdc.gov/ticks/data-research/facts-stats/tickborne-pathogen-surveillance-1.html)
(accessed 2026-10-02) describes pathogen detections in host-seeking ticks; this
does not establish a pathogen establishment threshold or sampled-negative rule.
The frozen governed source documentation, not current website prose alone,
must support any future executable rule.
