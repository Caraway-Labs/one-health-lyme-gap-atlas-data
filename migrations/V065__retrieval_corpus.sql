-- DEV-only versioned Research Assistant retrieval corpus (derived projection).
-- Chunk rows are rebuildable from approved PMC artifacts; they are not
-- immutable extraction-attempt evidence and may be replaced per rules version.
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

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT SELECT, INSERT, UPDATE ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW GOVERNANCE.V_RETRIEVAL_CORPUS_BUILD_METRICS
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT SELECT ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS
  TO ROLE OH_LYME_DEV_PMC_AUDITOR;
GRANT SELECT ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS
  TO ROLE OH_LYME_DEV_PMC_AUDITOR;
GRANT SELECT ON VIEW GOVERNANCE.V_RETRIEVAL_CORPUS_BUILD_METRICS
  TO ROLE OH_LYME_DEV_PMC_AUDITOR;
