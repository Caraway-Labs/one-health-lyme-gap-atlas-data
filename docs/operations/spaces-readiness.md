# Bounded DEV Spaces readiness

This is a metadata-only prerequisite, not acquisition or governed ingestion.
Use generic `run-ingestion.yml` operation `spaces-readiness`, DEV/Tier B,
`publish=false`, `recapture=false`, exact reviewed green main SHA, and optional
`candidate_keys_json` containing at most 16 known existing `dev/` object keys.
The workflow must first be reviewed and merged. Do not dispatch the draft.

The existing protected DEV identity stays in its environment. The probe pins
`sfo3`, `https://sfo3.digitaloceanspaces.com`, bucket
`one-health-lyme-gap-atlas-data-dev` and prefix `dev/`. It makes one bucket HEAD,
one LIST (at most 100 entries, no pagination), and at most 16 object HEADs.
SDK retry attempts are disabled; connect/read timeouts are 5/10 seconds and the
job has a five-minute ceiling. No object bodies, PUT/DELETE, ACL changes,
requester-pays requests, SQL, ingestion or credential export are performed.

Truncated LIST is explicit and never proves absence. Candidate HEAD failure
blocks the probe with sanitized status; it does not declare an object absent.
ETag is metadata, not asserted as a SHA-256. Read access is not write permission;
full byte identity remains unverified. Successful inspection is no authorization
to upload, publish, delete or expand access. Bounded metadata requests may have
provider accounting; this is not a claim of zero billing.

DATA #594 records the 2025 CONUS staging decision with official Amazon S3
preferred, exact manifest/spend ceiling pending, and Snowflake execution held.
The MRLC ZIP alternative does not replace the S3 contract silently.
