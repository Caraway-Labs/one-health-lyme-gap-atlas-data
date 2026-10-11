# CDC EID Expedited: exact DEV admission package

Status: reviewed candidate for a separately authorized, single-source DEV
registration. No registration or HTTP acquisition is part of this package.

The project owner approved the conservative source-policy direction under
`DATA-132-135-EID-ADMISSION-2026-10-09` on October 9, 2026 (Denver time).
The source document's `reviewed_at` is the UTC time the agent recorded that
approval in this package, not a claimed timestamp of the owner's UI action.
Protected read-only DEV preflight run
[38010384030](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38010384030)
used the migration-service identity on merged commit
`c04fc32aa146153f5cca23e50111e8adddbf4828`. It reported EID `ABSENT`,
object prerequisites passed, and `writes=false`. Thus version **1** is the
next live EID registry version at that checkpoint. The fixed registration
checks absence again under the serialization guard and fails if this changes.

The exact source document is
`config/intelligence/cdc-eid-expedited-source-v1.json`. Its canonical JSON
SHA256 is `51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4`.
The matching executable receipt is the sole entry in
`config/intelligence/pilot-policy-receipts.json`. The receipt cannot approve
itself: the normal runtime must independently read the same immutable source
version and hash from DEV.

| Decision | Reviewed value |
| --- | --- |
| Source | `cdc-eid-expedited`; CDC Emerging Infectious Diseases Expedited RSS |
| Endpoint | `https://wwwnc.cdc.gov/eid/rss/expedited.xml` |
| Cadence | Daily poll; no claim that CDC publishes daily |
| Publication | Title, link, language, publisher date; unknown dates remain unknown |
| Withheld | Descriptions, article bodies, public excerpts, image values/bytes, logos |
| Rights | [CDC use of agency materials](https://www.cdc.gov/other/agencymaterials.html): CDC attribution, free-original link, prominent nonendorsement, third-party exceptions |
| Retention | `cdc-eid-expedited-metadata-raw-30d-v1`, bound to `intelligence-raw-30d-v1`; raw expiry from immutable successful capture time |
| Artifacts | `CDC_EID_RESTRICTED_RAW_30D_V1`; private raw, no public artifact URL |
| Native policy | `cdc-eid-expedited-native-metadata-v1`, bound to the source SHA256; six permitted paths from the historical value-free inventory |
| Limits | 2 MiB, 250 items, 30 seconds, no redirects, one attempt |

The historical bounded metadata capture was at
`2026-10-03T03:06:52.954325Z`. The first authorized live run must recheck
availability. CDC's agency-materials guidance does not grant third-party image
or article reuse; this package retains no such values and links to originals.

## Exact registration path, after separate owner authorization

Use the reviewed fixed `deploy-dev.yml` mode on the exact merged, green main
commit of this package. It has no arbitrary SQL input, cannot dispatch a
migration, rejects a mixed diagnostic/pending set, checks the migration-service
identity and approved source hash, and inserts only this DEV source version.
Replace `<REVIEWED_GREEN_MAIN_SHA>` with that verified 40-character commit:

```text
gh workflow run deploy-dev.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f register_eid_expedited_dev=true -f expected_pending_json='[]' -f reviewed_commit=<REVIEWED_GREEN_MAIN_SHA> -f feed_preflight_accounting_confirmed=true
```

Before dispatch, verify the owner approval explicitly covers this exact
document, receipt, checksum, and command; the cleanup-service identity and
DEV-bucket delete key must be provisioned before the subsequent acquisition.
Registration does not fetch CDC data or activate cleanup. After registration,
use the existing fixed intelligence preflight to verify the exact live row and
receipt before one bounded DEV run.
