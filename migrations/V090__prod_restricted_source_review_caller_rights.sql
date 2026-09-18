-- Epic #252: the production restricted-source decision procedure is invoked
-- only by the steward-facing owner role.  V087 was created by the migration
-- deployer, whose owner-rights execution cannot update source-version state.
-- Execute as the approved caller instead, and grant the one missing status
-- transition privilege to the Streamlit-owner role.  The pipeline runtime has
-- neither this table privilege nor USAGE on the procedure.
USE DATABASE {{ DATABASE }};

GRANT UPDATE ON TABLE GOVERNANCE.DATA_SOURCE_VERSIONS
  TO ROLE OH_LYME_PROD_STREAMLIT_OWNER;

ALTER PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD(
  VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR, VARCHAR
) EXECUTE AS CALLER;
