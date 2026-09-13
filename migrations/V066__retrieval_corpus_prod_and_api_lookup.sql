-- Env-neutral retrieval corpus publication + procedure-only API provenance lookup.
-- Supersedes ADR 0025 DEV-only limits for table publication (ADR 0026).
-- Units remain a rebuildable projection; extraction attempt history is untouched.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS (
  build_id VARCHAR PRIMARY KEY,
  corpus_rules_version VARCHAR NOT NULL,
  rules_sha256 VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  papers_considered NUMBER NOT NULL DEFAULT 0,
  papers_admitted NUMBER NOT NULL DEFAULT 0,
  papers_excluded_unapproved NUMBER NOT NULL DEFAULT 0,
  chunks_written NUMBER NOT NULL DEFAULT 0,
  empty_chunk_rejections NUMBER NOT NULL DEFAULT 0,
  duplicate_chunk_rejections NUMBER NOT NULL DEFAULT 0,
  missing_provenance_rejections NUMBER NOT NULL DEFAULT 0,
  corpus_content_sha256 VARCHAR,
  redacted_error VARCHAR,
  started_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  finished_at TIMESTAMP_LTZ,
  CONSTRAINT ck_retrieval_corpus_build_status CHECK (
    status IN ('running', 'completed', 'failed')
  )
);

CREATE TABLE IF NOT EXISTS KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS (
  unit_id VARCHAR NOT NULL,
  corpus_rules_version VARCHAR NOT NULL,
  build_id VARCHAR NOT NULL,
  pmid VARCHAR NOT NULL,
  pmcid VARCHAR NOT NULL,
  artifact_id VARCHAR NOT NULL,
  object_key VARCHAR NOT NULL,
  jats_sha256 VARCHAR NOT NULL,
  text_sha256 VARCHAR NOT NULL,
  contribution_sha256 VARCHAR NOT NULL,
  chunk_index NUMBER NOT NULL,
  char_start NUMBER NOT NULL,
  char_end NUMBER NOT NULL,
  section_label VARCHAR NOT NULL,
  unit_text VARCHAR NOT NULL,
  unit_text_sha256 VARCHAR NOT NULL,
  built_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  PRIMARY KEY (corpus_rules_version, unit_id),
  UNIQUE (corpus_rules_version, pmid, chunk_index)
);

CREATE OR REPLACE VIEW GOVERNANCE.V_RETRIEVAL_CORPUS_BUILD_METRICS AS
SELECT
  build_id,
  corpus_rules_version,
  rules_sha256,
  status,
  papers_considered,
  papers_admitted,
  papers_excluded_unapproved,
  chunks_written,
  empty_chunk_rejections,
  duplicate_chunk_rejections,
  missing_provenance_rejections,
  corpus_content_sha256,
  redacted_error,
  started_at,
  finished_at
FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS;

-- Do not CREATE ROLE here: the governed pipeline deployer lacks ACCOUNT CREATE ROLE.
-- DEV auditor SELECT already landed in V065 (OH_LYME_DEV_PMC_AUDITOR). PROD auditor
-- SELECT is deferred until OH_LYME_PROD_PMC_AUDITOR is provisioned out of band.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT, UPDATE ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW GOVERNANCE.V_RETRIEVAL_CORPUS_BUILD_METRICS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_LOOKUP_RETRIEVAL_CORPUS_PROVENANCE(
  P_PMIDS ARRAY
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  invalid_input EXCEPTION (-20621, 'At most 20 PMIDs may be looked up');
  pmid_count NUMBER;
  result VARIANT;
BEGIN
  IF (P_PMIDS IS NULL) THEN
    RETURN ARRAY_CONSTRUCT();
  END IF;
  SELECT COUNT(*) INTO :pmid_count FROM TABLE(FLATTEN(INPUT => :P_PMIDS));
  IF (pmid_count > 20) THEN
    RAISE invalid_input;
  END IF;
  SELECT COALESCE(ARRAY_AGG(OBJECT_CONSTRUCT(
      'pmid', pmid,
      'pmcid', pmcid,
      'corpus_unit_ids', corpus_unit_ids,
      'section_labels', section_labels,
      'corpus_rules_version', corpus_rules_version,
      'artifact_id', artifact_id,
      'contribution_sha256', contribution_sha256,
      'jats_sha256', jats_sha256
    )), ARRAY_CONSTRUCT())
    INTO :result
    FROM (
      SELECT
        u.pmid AS pmid,
        ANY_VALUE(u.pmcid) AS pmcid,
        ARRAY_AGG(DISTINCT u.unit_id) WITHIN GROUP (ORDER BY u.unit_id) AS corpus_unit_ids,
        ARRAY_AGG(DISTINCT u.section_label) WITHIN GROUP (ORDER BY u.section_label)
          AS section_labels,
        ANY_VALUE(u.corpus_rules_version) AS corpus_rules_version,
        ANY_VALUE(u.artifact_id) AS artifact_id,
        ANY_VALUE(u.contribution_sha256) AS contribution_sha256,
        ANY_VALUE(u.jats_sha256) AS jats_sha256
      FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS u
      JOIN TABLE(FLATTEN(INPUT => :P_PMIDS)) selected
        ON u.pmid = selected.value::VARCHAR
      WHERE u.corpus_rules_version = 'retrieval-corpus-v1'
      GROUP BY u.pmid
    );
  RETURN :result;
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_LOOKUP_RETRIEVAL_CORPUS_PROVENANCE(ARRAY)
  TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
