-- Vocabulary topic rows for intelligence item revisions.
-- Readers use the v1 projection. The pipeline runtime may merge rows.
-- Captured item documents stay unchanged.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS CONFORMED.INTELLIGENCE_ITEM_TOPICS (
    item_id VARCHAR(64) NOT NULL,
    revision_id VARCHAR(64) NOT NULL,
    topic_id VARCHAR(64) NOT NULL,
    vocabulary_version VARCHAR(16) NOT NULL,
    matched_field VARCHAR(32) NOT NULL,
    matched_term VARCHAR(4096) NOT NULL,
    computed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (item_id, revision_id, topic_id, vocabulary_version)
);

GRANT SELECT, INSERT, UPDATE ON TABLE CONFORMED.INTELLIGENCE_ITEM_TOPICS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;

CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_ITEM_TOPICS_V1 AS
SELECT item_id,
       revision_id,
       topic_id,
       vocabulary_version,
       matched_field,
       matched_term,
       computed_at
FROM CONFORMED.INTELLIGENCE_ITEM_TOPICS
WHERE vocabulary_version = 'v1';

GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_ITEM_TOPICS_V1
    TO ROLE OH_LYME_{{ ENV }}_READ;
