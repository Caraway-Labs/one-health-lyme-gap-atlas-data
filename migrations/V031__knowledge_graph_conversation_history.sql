USE DATABASE {{ DATABASE }};

-- Conversation history is returned only through the opaque capability-token
-- boundary. The API still receives no direct SELECT privilege on user content.
CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_READ_KG_CONVERSATION_HISTORY(
  CONVERSATION_ID VARCHAR, TOKEN_HASH VARCHAR, MAX_TURNS NUMBER
)
RETURNS ARRAY
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  unauthorized EXCEPTION (-20111, 'Conversation capability is invalid');
  invalid_turn_count EXCEPTION (-20112, 'MAX_TURNS must be between 1 and 12');
  matching_count NUMBER;
  turns ARRAY;
BEGIN
  IF (MAX_TURNS < 1 OR MAX_TURNS > 12) THEN
    RAISE invalid_turn_count;
  END IF;
  SELECT COUNT(*) INTO :matching_count
    FROM GOVERNANCE.KG_CONVERSATIONS
    WHERE conversation_id = :CONVERSATION_ID AND token_hash = :TOKEN_HASH
      AND expires_at > CURRENT_TIMESTAMP();
  IF (matching_count <> 1) THEN RAISE unauthorized; END IF;
  SELECT COALESCE(
    ARRAY_AGG(OBJECT_CONSTRUCT('role', role, 'content', body))
      WITHIN GROUP (ORDER BY created_at ASC, turn_id ASC),
    ARRAY_CONSTRUCT()
  ) INTO :turns
  FROM (
    SELECT role, body, created_at, turn_id
    FROM GOVERNANCE.KG_CONVERSATION_TURNS
    WHERE conversation_id = :CONVERSATION_ID AND role IN ('user', 'assistant')
    ORDER BY created_at DESC, turn_id DESC
    LIMIT :MAX_TURNS
  );
  RETURN :turns;
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_READ_KG_CONVERSATION_HISTORY(VARCHAR, VARCHAR, NUMBER)
  TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
