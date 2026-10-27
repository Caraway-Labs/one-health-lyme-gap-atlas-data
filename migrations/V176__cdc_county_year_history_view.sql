-- Story #855. Routine migration for DEV and PROD.
-- V171 through V175 are reserved by other stories. This file is not held back
-- and is not environment-only.
-- The view reads the current semantic release only. It does not filter report
-- year, so story #856 can admit 2022 by changing the builder year set.
-- It does not read county-context columns or retained lineage objects.
-- The release builder reads CONFORMED.CONFORMED_CDC_LYME_QTBI_XD4I. This view
-- returns rows only after that release is the current pointer.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW PRESENTATION.CDC_LYME_COUNTY_YEAR_HISTORY_V1
COPY GRANTS AS
SELECT CAST(o.fips AS VARCHAR(5)) AS county_fips,
       CAST(o.value:geography_vintage AS VARCHAR) AS geography_vintage,
       CAST(o.value:state_fips AS VARCHAR(2)) AS state_fips,
       CAST(TRY_TO_NUMBER(o.temporal_window) AS NUMBER(4, 0)) AS report_year,
       DATE_FROM_PARTS(TRY_TO_NUMBER(o.temporal_window), 1, 1) AS period_start,
       DATE_FROM_PARTS(TRY_TO_NUMBER(o.temporal_window), 12, 31) AS period_end,
       CAST(o.value:methodology_era AS VARCHAR) AS methodology_era,
       CAST(o.value:methodology_era_id AS VARCHAR) AS methodology_era_id,
       CAST(o.value:methodology_note AS VARCHAR) AS methodology_note,
       CAST(o.measure_id AS VARCHAR) AS measure_id,
       CAST(o.value:case_count AS NUMBER) AS case_count,
       CAST(o.value_state AS VARCHAR) AS value_state,
       CAST(o.value:is_censored AS BOOLEAN) AS is_censored,
       CAST(o.value:censor_reason AS VARCHAR) AS censor_reason,
       CAST(r.release_id AS VARCHAR) AS release_id,
       CAST(o.source_version_id AS VARCHAR) AS source_version_id
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_OBSERVATIONS o
  ON o.release_id = r.release_id
WHERE p.pointer_key = 'ATLAS'
  AND o.measure_id IN (
    'human_case_count_published_floor_annual',
    'state_unallocated_records_annual'
  );

GRANT SELECT ON VIEW PRESENTATION.CDC_LYME_COUNTY_YEAR_HISTORY_V1
  TO ROLE OH_LYME_{{ ENV }}_READ;

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_METHODOLOGY_METADATA_V
COPY GRANTS AS
WITH approved_methodologies AS (
    SELECT column1 AS measure_id, column2 AS methodology_id,
           column3 AS approved_text, column4 AS approved_limitation
    FROM VALUES
      ('human_status', 'human_source_native_status_mapping_v1',
       'source-native status mapping',
       'Published floors are not complete incidence.'),
      ('case_count_floor_2023', 'human_confirmed_probable_case_floor_v1',
       'x5j9 confirmed plus probable', 'Privacy-protected floor.'),
      ('incidence_floor_2023', 'human_case_floor_population_incidence_v1',
       'case floor divided by population', 'Not complete incidence.')
)
SELECT a.methodology_id, m.measure_id, m.methodology,
       r.methodology_version, m.limitation,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.CURRENT_MEASURE_METADATA_V m
  ON m.release_version = r.release_id
JOIN approved_methodologies a
  ON a.measure_id = m.measure_id
 AND a.approved_text = m.methodology
 AND a.approved_limitation = m.limitation
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id
 AND s.source_key = 'human'
 AND s.source_id = 'cdc_lyme'
 AND s.dataset_id = 'x5j9-wybp'
WHERE p.pointer_key = 'ATLAS'
UNION ALL
SELECT CASE m.measure_id
         WHEN 'human_case_count_published_floor_annual'
           THEN 'human_case_count_published_floor_annual_v1'
         ELSE 'state_unallocated_records_annual_v1'
       END AS methodology_id,
       m.measure_id, m.methodology,
       r.methodology_version, m.limitation,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_MEASURES m
  ON m.release_id = r.release_id
 AND m.measure_id IN (
      'human_case_count_published_floor_annual',
      'state_unallocated_records_annual'
    )
 AND m.methodology = 'CDC reported Lyme surveillance cases by county of residence. Report year 2022 is not in this release. The 2008-2021 case definition is not directly comparable with the 2022 onward definition. These counts are not infection incidence.'
 AND m.limitation = 'A null case count is not a reported zero. Sex and age strata are not released. Legacy Connecticut counties use geography class ct_legacy_county_codes and geography vintage legacy_ct_counties_2008_2022 and have no atlas geometry. Report year 2022 is not in this release.'
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id
 AND s.source_key = 'cdc_historical'
WHERE p.pointer_key = 'ATLAS';

GRANT SELECT ON VIEW PRESENTATION.CURRENT_METHODOLOGY_METADATA_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
