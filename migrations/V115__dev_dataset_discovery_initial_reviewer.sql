-- DEV-only initial human reviewer onboarding. The role grant to this named
-- human user was verified separately; this row authorizes only the reviewed
-- Dataset Discovery review/handoff procedures. No source approval is granted.
USE DATABASE {{ DATABASE }};

INSERT INTO DATASET_DISCOVERY.REVIEWER_ALLOWLIST
  (reviewer_user, is_active, granted_at, granted_by)
SELECT 'MATTHEWCARAWAY', TRUE, CURRENT_TIMESTAMP(), CURRENT_USER()
WHERE NOT EXISTS (
  SELECT 1 FROM DATASET_DISCOVERY.REVIEWER_ALLOWLIST
  WHERE reviewer_user = 'MATTHEWCARAWAY' AND is_active = TRUE
);
