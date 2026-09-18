-- Epic #252: the production restricted-source decision procedure is invoked
-- only by the steward-facing owner role. V087 was created by the migration
-- deployer, whose owner-rights execution cannot update source-version state.
-- Execute as the approved caller instead. The separately authorized bootstrap
-- grant is documented in deployment-promotion.md because this migration role
-- must not grant production table privileges. The pipeline runtime has neither
-- this table privilege nor USAGE on the procedure.
USE DATABASE {{ DATABASE }};

ALTER PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD(
  VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR, VARCHAR
) EXECUTE AS CALLER;
