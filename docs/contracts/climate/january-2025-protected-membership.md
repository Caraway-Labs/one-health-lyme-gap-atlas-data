# Protected frozen membership inspection

The existing canonical pilot `inspect` action succeeded on reviewed main in run
37095612795: 389856 revisions and normalized rows, 1560 completed partitions,
and exact retained NOAA/Census artifact hashes. This is actual runtime visibility,
separate from unavailable local read/owner visibility. No new grant or credential
is required to use that existing service route.

`nclimgrid-pilot-measure --action frozen-membership` adds the remaining bounded
read to the same canonical `run-ingestion.yml` workflow. It requires reviewed main
and successful exact-head quality, DEV/Tier B, the fixed definition/run, and false
recapture/publication flags. The actual existing runtime identity is checked
before all SELECTs. The wrapper accepts no other run or local output fallback.

It validates the completed run and both retained hashes/sizes, reads the current
PUBLISHED ATLAS release and its five-source annual manifest, and freezes the
sorted selected capture IDs and five-tuple membership digest used by publication.
The result is capped at the fixed January count plus one rejection row. Extra,
missing, unordered or malformed rows and pointer movement fail atomically without
replacing an existing artifact. No warehouse object or provenance row is written.

The full ID list and unchanged current annual manifest are retained in a 14-day
workflow artifact. Stdout contains counts and digests only, with no principal,
credential, private endpoint or source row payload. Its status is explicitly
READ_ONLY_CANDIDATE_NOT_PUBLICATION. The artifact does not approve a source,
publish a release or prove PROD parity.

After independent review/merge and main quality, dispatch the existing workflow
on main with operation `nclimgrid-pilot-measurement`, action `frozen-membership`,
the actual reviewed full `reviewed_commit`, the retained selected run and exact
January definition. Download and verify the artifact digest before preparing the
release manifest. Preserve its actual annual source slots; do not copy an older
static annual manifest. The complete manifest still requires independent review,
the actual technical review record, target payload/storage checks and protected
publication. This is no additional Matthew product-acceptance question.
