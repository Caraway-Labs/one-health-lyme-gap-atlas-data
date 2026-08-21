USE DATABASE {{ DATABASE }};

-- Reconcile only versions that can never be legitimate: the recorded decision
-- identifier is absent from the append-only review ledger. Retention is
-- preserved; the version is retired rather than deleted or rewritten.
UPDATE GOVERNANCE.DATA_SOURCE_VERSIONS AS version
SET status = 'RETIRED', retired_at = CURRENT_TIMESTAMP()
WHERE version.retired_at IS NULL
  AND version.approved_decision_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS AS decision
    WHERE decision.manual_review_decision_id = version.approved_decision_id
  );
