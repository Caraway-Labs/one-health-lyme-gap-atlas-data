-- DATA #495: preserve fractional-dollar finalization values when known.
-- Unknown provider charges remain NULL; reservations are cost bounds, not bills.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(
  WORKLOAD VARCHAR, REQUEST_ID VARCHAR, STATUS VARCHAR, ACTUAL_COST_USD NUMBER(12,6)
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

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(VARCHAR, VARCHAR, VARCHAR, NUMBER)
  TO ROLE OH_LYME_PROD_RUNTIME;
