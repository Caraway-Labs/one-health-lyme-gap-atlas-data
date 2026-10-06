# January consumer dependency, separate from history

Initial planning baseline DATA main `819dde4974d4bd0c6acc3235dfaeeb146098233a`.
That planning reconciliation executed no Snowflake query, source download,
ingestion, grant or deployment. Subsequent diagnostic evidence is recorded below;
the dated API handoff is not a new consumer readback.

API #84's October 6 handoff reports 45 reader/probe tests and intended PROD_READ
identity verification. Exact metadata-view read failed `002003`; public discovery
still returns 14 measures without climate. No alternate role was tried.
See https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-api/issues/84#issuecomment-6009517013.

Reusable implementation: `climate_release.py` validates
`atlas-january-climate-release-extension-v1`; `climate_publication.py` reconstructs
the retained candidate; V136 defines
`PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V` and
`PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V`. The four metadata revisions
and two actual conditional source decisions are retained by #580/#582, preserving
UNKNOWN original decision time. The accepted run is
`c2eb2146-005d-44d2-bac4-e2805ca42577`; 389856 rows and repeated projection digest
`1e6b9809a5266d7cb3b4851f861835fdfddcf0d4f136a02d14e7e436806f5618`.

PR #584 delivered a SELECT-only frozen-membership exporter on main. Run
37098434706 passed exact-main and DEV-scope guards but failed
`FROZEN_MEMBERSHIP_READ_UNAVAILABLE`; zero artifacts were retained. This generic
diagnostic does not identify the failing SELECT or classify absence versus access.
Do not silently widen its runtime identity or substitute another role.

V137/#604 audits semantic observations joined to source records. It has no
`normalized_sha256` projection and is anchored on already-assembled semantic
observations. It does not freeze all unpublished January revisions or grant the
runtime SELECT on semantic release pointers/manifests. Thus closure of #604/#605
does not establish that the January export now works. V071's recorded grants
separate presentation owner/migration from runtime; this is a possible boundary,
not proof of which statement failed in the live run.

The original next diagnostic increment was to add finite failed-stage and allowlisted
SDK error-category evidence to the existing exporter, with privacy regression
tests; independently review it before any bounded paid read. Verify that exact
source-specific boundary using the existing approved identity. A grant request
requires a proven object/owner and principal/privilege tuple; none is established
by the generic export failure or API `002003` alone.

## Checkpoint after the bounded diagnostic

Matthew's actual January product approval remains: "Yes, I approve ingesting the
data, making sure it's in Snowflake, getting it modeled correctly in Snowflake,
and then exposing it through our API." It authorizes the bounded January product
work; it supplies no missing checksum, lineage, provenance, reader grant or PROD
publication evidence. Historical expansion remains deferred.

PR #616 merged `ef0aa357f7b79cc002233f64475eb16f65aeb3e6`; exact-main CI
`37420820267` passed 3,301 tests. Its one approved read-only workflow run
`37421002704` completed, but the diagnostic receipt is `BLOCKED` at `PREFLIGHT`,
`WAREHOUSE_COST_ASSUMPTIONS_UNVERIFIED`: two identity/SHOW statements, 1.659 seconds.
No membership query or export occurred. The original receipt did not retain the
SHOW fields or the failed predicate; the exact mismatch cannot be recovered.
Do not infer an SDK defect, missing object or missing grant.

PR #620 merged `f8e0626fbff3af9d0588251cfa4bbd10e3a1acb4`; exact-main CI
`37423114986` passed 3,312 tests. It preserves all six warehouse predicates,
records safe preflight fields/types and failed checks, and caps a possible
follow-up using the existing watchdog/cursor deadline at fifty execution seconds.
The five-minute job window and sixty-second cleanup reserve remain intact. No
source/membership guards, identity, warehouse setting or grants were changed.

The corrected diagnostic has not run. One additional read-only diagnostic,
capped at 50 execution seconds with unchanged guards and no retries, awaits
Matthew's explicit approval before dispatch.

The original full reservation is US$3.3295833333. At the verified public
US$6/credit forecast the proposed follow-up reservation is US$1.6141666667,
aggregate US$4.94375. These include separate noncompute reserves and an idle tail;
they are forecasts, not actual charges or a statement of remaining budget.
Actual billed dollars remain null. Usage history was not queried because the
preflight failed. Another execution must first verify reviewed current main and its exact CI; stale
SHA, pricing or runtime evidence blocks it.

API #84 still needs verified frozen membership/digest and donor manifest, the
reviewed January extension, target parity/storage proof, and the existing protected
publication/reader-readback path. Neither merged diagnostic PR establishes full
January publication, PROD object absence, consumer availability or API acceptance.
Keep DATA #443 and API #84 open; no Web changes or historical execution are included.

After verified full ordered IDs and five-tuple digest, preserve the actual annual
donor manifest, assemble and review the exact January extension, prove target
source/version/artifact/payload and large-manifest storage round trip, and use
the existing protected semantic build/publication path. Target view ownership
and intended-reader SELECT/readback remain separate evidence. #496's dated
handoff records DEV-only V136 and owner-supplied PROD inventory, not a current
PROD climate release receipt. January product approval is not reopened.

Coordinate any shared migration or release edits with DATA #429 and feed
#132/#135 owners before reserving a number. This PR reserves no migration and
changes no publication implementation. API's first January response must not
wait for the 1985 historical proof; no competing endpoint/schema is proposed.
