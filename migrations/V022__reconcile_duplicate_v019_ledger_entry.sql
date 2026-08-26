USE DATABASE {{ DATABASE }};

-- V019 was recorded twice with the identical source checksum during the
-- earlier grant deployment. Preserve both immutable audit records rather than
-- deleting history. This forward-only reconciliation validates that the
-- duplicate is limited to those two identical V019 records before registering
-- this migration.
SELECT 1 / IFF(COUNT(*) = 2 AND COUNT(DISTINCT sha256) = 1, 1, 0)
  AS v019_duplicate_ledger_reconciled
FROM GOVERNANCE.SCHEMA_MIGRATIONS
WHERE version = 'V019';
