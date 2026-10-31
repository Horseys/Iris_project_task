CREATE SCHEMA IF NOT EXISTS iris_staging;

CREATE TABLE IF NOT EXISTS iris_staging.socio_demographics_staging (
    source_table_code VARCHAR(32) NOT NULL,
    county_key VARCHAR(5) NOT NULL,
    observation_year BIGINT NOT NULL,
    county_name TEXT NOT NULL,
    registrations BIGINT,
    deregistrations BIGINT,
    unit VARCHAR(32) NOT NULL,
    source_url TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    source_retrieved_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_socio_demographics_staging
        PRIMARY KEY (source_table_code, county_key, observation_year),
    CONSTRAINT ck_socio_demo_county_key
        CHECK (county_key ~ '^[0-9]{5}$'),
    CONSTRAINT ck_socio_demo_registrations_nonnegative
        CHECK (registrations IS NULL OR registrations >= 0),
    CONSTRAINT ck_socio_demo_deregistrations_nonnegative
        CHECK (deregistrations IS NULL OR deregistrations >= 0)
);
