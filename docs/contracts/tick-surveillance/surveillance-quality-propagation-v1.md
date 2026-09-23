# Surveillance-quality propagation v1

Status: Implemented bounded fixture-backed transformation proof for Story #166
Owner: Atlas data stewardship and engineering
Schema: `surveillance-quality-propagation-v1.schema.json`
Input quality method: `surveillance-quality-profile-v1`

## Purpose and boundary

This contract defines a pure, in-memory propagation envelope for one or more
already canonical surveillance observations and their existing v1 quality
profiles. It proves that source quality, missingness, limitations,
representativeness, comparability restrictions, source/version references, and
component reason codes survive a transformation boundary. It is not a
scientific metric, scientific aggregation, source pool, county generalization,
prevalence calculation, effort-normalized abundance calculation, score,
weighting model, uncertainty/confidence model, persistent store, public release
behavior, or a replacement for #188/#191/#193.

## Deterministic rules

- Inputs remain distinct and retain every v1 component state and reason code.
- A dimension's summary state is `UNKNOWN` if any input is `UNKNOWN`; otherwise
  it is `ASSESSED` if any input is `ASSESSED`; it is `NOT_APPLICABLE` only when
  every input is `NOT_APPLICABLE`. This is conservative metadata propagation,
  not a quality rank or aggregation rule.
- `NOT_APPLICABLE` is never treated as poor quality. States are never averaged,
  and no input is silently selected as "best."
- Reason codes and textual limitations are ordered by first occurrence and
  de-duplicated exactly. Transform-added reason codes/limitations are separate
  fields and never replace inherited evidence.
- Site/event inputs retain `REPRESENTATIVENESS_NOT_COUNTY_REPRESENTATIVE`.
  This contract has no method that can supersede it.
- `METHOD_COMPARABILITY_NOT_ESTABLISHED` and incompatible-method evidence are
  preserved but do not block this metadata-only projection, because it pools no
  value and makes no comparability decision.
- Retained input values are copied only to preserve native zero/null evidence;
  this projection computes no numeric result and never invents effort, testing
  denominators, prevalence, normalized abundance, or biological zero.

## Multi-input, join, conflict, and denominator behavior

Multiple inputs are a metadata collection only. The envelope retains every
input profile and source/version reference instead of calculating a pooled,
county, prevalence, or normalized-abundance value. It therefore defines no
scientific aggregation rule. A caller may carry inputs from an existing join,
but the envelope preserves limitations and components from both sides; a
successful technical join never establishes scientific comparability.

Conflicting or mixed limitations remain as distinct first-seen values. The
conservative component summary never selects the more favorable state and its
per-input component list retains the original conflict. A missing/unknown
effort or unavailable testing denominator remains visible in the inherited
reason codes and profile states. Zero tested does not create prevalence, and a
valid documented input zero is copied as an input fact only, never treated as
coverage, absence, or a calculated output.

## Consumer-safe serialization

`serialize_safe_propagation` retains transformation ID/version, quality method,
safe canonical IDs, source dataset/version and canonical method version,
propagated components, and limitation/reason-code fields. It excludes retained
input values, artifact IDs and URIs, signed URLs, credentials, and raw/private
payloads. It is a safe metadata projection, not a public-release authorization.

## Remaining boundaries

This contract does not approve any future downstream metric. A formula,
pooling/aggregation rule, county claim, comparability decision, new confidence
model, storage design, or public consumer contract needs its owning reviewed
story and methodology.
