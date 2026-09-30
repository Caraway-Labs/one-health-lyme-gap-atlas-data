-- DATA #495: preserve fractional-dollar reservations in the existing PROD contract.
-- Bootstrap transfers the existing procedure to the dedicated budget owner,
-- preserving the three existing USAGE grants, and grants that owner INSERT on
-- LLM_BUDGET_USAGE. The protected migration service then executes this file.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(
  WORKLOAD VARCHAR, REQUEST_ID VARCHAR, PROVIDER VARCHAR, MODEL_IDENTIFIER VARCHAR,
  ESTIMATED_COST_USD NUMBER(12,6), DAILY_LIMIT_USD NUMBER(12,6), MONTHLY_LIMIT_USD NUMBER(12,6)
)
COPY GRANTS
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  daily_used NUMBER(12,6);
  monthly_used NUMBER(12,6);
  allowed BOOLEAN;
BEGIN
  SELECT COALESCE(SUM(estimated_cost_usd),0) INTO :daily_used FROM GOVERNANCE.LLM_BUDGET_USAGE
    WHERE workload = :WORKLOAD AND status IN ('reserved','used')
      AND recorded_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP());
  SELECT COALESCE(SUM(estimated_cost_usd),0) INTO :monthly_used FROM GOVERNANCE.LLM_BUDGET_USAGE
    WHERE workload = :WORKLOAD AND status IN ('reserved','used')
      AND recorded_at >= DATE_TRUNC('month', CURRENT_TIMESTAMP());
  allowed := daily_used + ESTIMATED_COST_USD <= DAILY_LIMIT_USD
             AND monthly_used + ESTIMATED_COST_USD <= MONTHLY_LIMIT_USD;
  IF (allowed) THEN
    INSERT INTO GOVERNANCE.LLM_BUDGET_USAGE (
      budget_usage_id, workload, request_id, provider, model_identifier,
      estimated_cost_usd, actual_cost_usd, status, recorded_at
    ) SELECT UUID_STRING(), :WORKLOAD, :REQUEST_ID, :PROVIDER, :MODEL_IDENTIFIER,
             :ESTIMATED_COST_USD, NULL, 'reserved', CURRENT_TIMESTAMP();
  END IF;
  RETURN OBJECT_CONSTRUCT('allowed', :allowed, 'daily_used_usd', :daily_used,
                          'monthly_used_usd', :monthly_used);
END;
$$;

-- COPY GRANTS retains the existing OH_LYME_PROD_RUNTIME, OH_LYME_PROD_READ,
-- and OH_LYME_API_READER grants without introducing new runtime privileges.
