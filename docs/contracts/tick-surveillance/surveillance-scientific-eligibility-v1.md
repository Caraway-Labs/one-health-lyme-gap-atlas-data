# Surveillance scientific eligibility v1

Status: Internal governed remediation candidate
Owner: Atlas data stewardship and engineering
Tuple table: `surveillance-scientific-eligibility-v1.json`
Mapping registry: `tick-surveillance-normalization-v1.json` version `1.0.4`

The tuple table lists the only publisher/source product/source version/source
vintage/construct combinations eligible for positive #171 states and #172
cohorts. CDC county-status cumulative vintage and NEON frozen release vintage
have distinct meanings. Version, retrieval date, observation date, or
cumulative-through date cannot substitute for the listed vintage. Adding a
tuple requires governed review; the table does not approve new acquisition or
publication.

For each required scientific field, the attestation helper additionally
requires one approved normalization rule for that exact publisher, dataset,
version, field, and construct role. It checks source value, canonical ID and
label, mapping status, registry identity, and aggregate flag. No global
canonical allowlist or foreign-source rule can establish eligibility.
