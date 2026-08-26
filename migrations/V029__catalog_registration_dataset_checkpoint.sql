USE DATABASE {{ DATABASE }};

-- A catalog metadata artifact can contain thousands of datasets. Persisting
-- this index lets a bounded registration pass resume within an artifact rather
-- than holding one Snowflake transaction until every dataset has been merged.
ALTER TABLE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
  ADD COLUMN IF NOT EXISTS next_dataset_offset NUMBER NOT NULL DEFAULT 0;
