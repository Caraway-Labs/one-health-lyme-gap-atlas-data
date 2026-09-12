-- DEV-only, append-only budget finalization. Reservations remain immutable;
-- failed finalizations release the reserved amount from the daily/monthly sum.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.LLM_BUDGET_FINALIZATIONS (
  budget_finalization_id VARCHAR PRIMARY KEY,
  workload VARCHAR NOT NULL,
  request_id VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  actual_cost_usd NUMBER(12,6),
  recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT ck_llm_budget_finalization_status CHECK (status IN ('used', 'failed')),
  UNIQUE (workload, request_id)
);

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(
  WORKLOAD VARCHAR, REQUEST_ID VARCHAR, STATUS VARCHAR, ACTUAL_COST_USD NUMBER
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  invalid_status EXCEPTION (-20611, 'Budget finalization status must be used or failed');
  missing_reservation EXCEPTION (-20612, 'Budget finalization requires an existing reservation');
  already_finalized EXCEPTION (-20613, 'Budget reservation was already finalized');
  reservation_count NUMBER;
  finalization_count NUMBER;
BEGIN
  IF (STATUS IS NULL OR STATUS NOT IN ('used', 'failed')) THEN RAISE invalid_status; END IF;
  SELECT COUNT(*) INTO :reservation_count FROM GOVERNANCE.LLM_BUDGET_USAGE
    WHERE workload = :WORKLOAD AND request_id = :REQUEST_ID AND status IN ('reserved', 'used');
  IF (reservation_count <> 1) THEN RAISE missing_reservation; END IF;
  SELECT COUNT(*) INTO :finalization_count FROM GOVERNANCE.LLM_BUDGET_FINALIZATIONS
    WHERE workload = :WORKLOAD AND request_id = :REQUEST_ID;
  IF (finalization_count <> 0) THEN RAISE already_finalized; END IF;
  INSERT INTO GOVERNANCE.LLM_BUDGET_FINALIZATIONS (
    budget_finalization_id, workload, request_id, status, actual_cost_usd, recorded_at
  ) SELECT UUID_STRING(), :WORKLOAD, :REQUEST_ID, :STATUS, :ACTUAL_COST_USD, CURRENT_TIMESTAMP();
  RETURN OBJECT_CONSTRUCT(
    'workload', :WORKLOAD,
    'request_id', :REQUEST_ID,
    'status', :STATUS,
    'actual_cost_usd', :ACTUAL_COST_USD
  );
END;
$$;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(
  WORKLOAD VARCHAR, REQUEST_ID VARCHAR, PROVIDER VARCHAR, MODEL_IDENTIFIER VARCHAR,
  ESTIMATED_COST_USD NUMBER, DAILY_LIMIT_USD NUMBER, MONTHLY_LIMIT_USD NUMBER
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  daily_used NUMBER;
  monthly_used NUMBER;
  allowed BOOLEAN;
BEGIN
  SELECT COALESCE(SUM(estimated_cost_usd),0) INTO :daily_used FROM GOVERNANCE.LLM_BUDGET_USAGE u
    WHERE workload = :WORKLOAD AND status IN ('reserved','used')
      AND recorded_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP())
      AND NOT EXISTS (
        SELECT 1 FROM GOVERNANCE.LLM_BUDGET_FINALIZATIONS f
        WHERE f.workload = u.workload AND f.request_id = u.request_id AND f.status = 'failed'
      );
  SELECT COALESCE(SUM(estimated_cost_usd),0) INTO :monthly_used FROM GOVERNANCE.LLM_BUDGET_USAGE u
    WHERE workload = :WORKLOAD AND status IN ('reserved','used')
      AND recorded_at >= DATE_TRUNC('month', CURRENT_TIMESTAMP())
      AND NOT EXISTS (
        SELECT 1 FROM GOVERNANCE.LLM_BUDGET_FINALIZATIONS f
        WHERE f.workload = u.workload AND f.request_id = u.request_id AND f.status = 'failed'
      );
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

GRANT SELECT, INSERT ON TABLE GOVERNANCE.LLM_BUDGET_FINALIZATIONS
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(VARCHAR, VARCHAR, VARCHAR, NUMBER)
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR, NUMBER, NUMBER, NUMBER)
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR, NUMBER, NUMBER, NUMBER)
  TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
