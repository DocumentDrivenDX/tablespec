CREATE OR REFRESH MATERIALIZED VIEW ingested_provider_directory
(
  CONSTRAINT not_null_provider_npi EXPECT (provider_npi IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        provider_npi                                                AS provider_npi,
        provider_name                                               AS provider_name,
        cast(try_to_timestamp(enrolled_date, 'MM/dd/yyyy') as date) AS enrolled_date,
        cast(is_active as boolean)                                  AS is_active
FROM raw_provider_directory;