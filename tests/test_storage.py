from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from task_cre_50.storage import (
    STAGING_SCHEMA,
    TARGET_TABLE_NAME,
    PersistenceError,
    build_upsert_statement,
    load_observations,
)
from task_cre_50.transform import Observation


def sample_observation() -> Observation:
    return Observation(
        county_key="01001",
        county_name="Flensburg, kreisfreie Stadt",
        observation_year=2024,
        registrations=11,
        deregistrations=2,
        unit="Anzahl",
        source_table_code="52311-01-04-4",
        source_url="https://www.regionalstatistik.de/source",
        source_updated_at=None,
        source_retrieved_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
    )


def test_upsert_targets_only_staging_and_has_stable_conflict_key() -> None:
    statement = build_upsert_statement([sample_observation()])
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert f"{STAGING_SCHEMA}.{TARGET_TABLE_NAME}" in sql
    assert "ON CONFLICT (source_table_code, county_key, observation_year)" in sql
    assert "IS DISTINCT FROM" in sql
    assert "xmax = 0" in sql
    assert "iris_core" not in sql


def test_empty_uri_is_rejected_before_any_database_access() -> None:
    with pytest.raises(PersistenceError, match="DB_URI is required"):
        load_observations("", [sample_observation()])


def test_upsert_rejects_duplicate_keys_in_one_batch() -> None:
    observation = sample_observation()

    with pytest.raises(ValueError, match="duplicate stable keys"):
        build_upsert_statement([observation, observation])
