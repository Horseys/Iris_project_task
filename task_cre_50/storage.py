from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    literal_column,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from task_cre_50.transform import Observation

STAGING_SCHEMA = "iris_staging"
TARGET_TABLE_NAME = "socio_demographics_staging"
KEY_COLUMNS = ("source_table_code", "county_key", "observation_year")

metadata = MetaData()
target_table = Table(
    TARGET_TABLE_NAME,
    metadata,
    Column("source_table_code", String(32), primary_key=True),
    Column("county_key", String(5), primary_key=True),
    Column("observation_year", BigInteger, primary_key=True),
    Column("county_name", Text, nullable=False),
    Column("registrations", BigInteger, nullable=True),
    Column("deregistrations", BigInteger, nullable=True),
    Column("unit", String(32), nullable=False),
    Column("source_url", Text, nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("source_retrieved_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("county_key ~ '^[0-9]{5}$'", name="ck_socio_demo_county_key"),
    CheckConstraint(
        "registrations IS NULL OR registrations >= 0",
        name="ck_socio_demo_registrations_nonnegative",
    ),
    CheckConstraint(
        "deregistrations IS NULL OR deregistrations >= 0",
        name="ck_socio_demo_deregistrations_nonnegative",
    ),
    schema=STAGING_SCHEMA,
)


class PersistenceError(RuntimeError):
    """Raised when staging-only persistence fails or the target is incompatible."""


@dataclass(frozen=True)
class PersistenceResult:
    inserted_count: int
    updated_count: int


def build_upsert_statement(rows: Sequence[Observation]) -> Insert:
    if not rows:
        raise ValueError("Cannot build a staging upsert for an empty batch")
    values = [_observation_values(row) for row in rows]
    insert_statement = postgresql_insert(target_table).values(values)
    excluded = insert_statement.excluded
    changed = or_(
        *(
            target_table.c[column].is_distinct_from(getattr(excluded, column))
            for column in (
                "county_name",
                "registrations",
                "deregistrations",
                "unit",
                "source_url",
                "source_updated_at",
            )
        )
    )
    statement = insert_statement.on_conflict_do_update(
        index_elements=[target_table.c[column] for column in KEY_COLUMNS],
        set_={
            "county_name": excluded.county_name,
            "registrations": excluded.registrations,
            "deregistrations": excluded.deregistrations,
            "unit": excluded.unit,
            "source_url": excluded.source_url,
            "source_updated_at": excluded.source_updated_at,
            "source_retrieved_at": excluded.source_retrieved_at,
        },
        where=changed,
    )
    return statement.returning(literal_column("(xmax = 0)").label("was_inserted"))


def load_observations(
    db_uri: str,
    rows: Sequence[Observation],
    *,
    batch_size: int = 500,
) -> PersistenceResult:
    if not db_uri:
        raise PersistenceError("DB_URI is required when --load-db is selected")
    if not rows:
        raise PersistenceError("No observations were provided for database loading")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    try:
        engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10},
        )
    except SQLAlchemyError as exc:
        raise PersistenceError(f"Could not configure DB_URI: {exc}") from exc

    try:
        if engine.dialect.name != "postgresql":
            raise PersistenceError("DB_URI must point to PostgreSQL 16")
        _validate_target(engine)
        inserted_count = 0
        updated_count = 0
        with engine.begin() as connection:
            for offset in range(0, len(rows), batch_size):
                batch = rows[offset : offset + batch_size]
                result = connection.execute(build_upsert_statement(batch))
                inserted_flags = result.scalars().all()
                inserted_count += sum(bool(flag) for flag in inserted_flags)
                updated_count += len(inserted_flags) - sum(
                    bool(flag) for flag in inserted_flags
                )
        return PersistenceResult(
            inserted_count=inserted_count,
            updated_count=updated_count,
        )
    except PersistenceError:
        raise
    except SQLAlchemyError as exc:
        raise PersistenceError(
            f"Staging transaction failed; all {len(rows)} rows were rolled back: {exc}"
        ) from exc
    finally:
        engine.dispose()


def _validate_target(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            server_version = int(
                connection.execute(text("SHOW server_version_num")).scalar_one()
            )
            if server_version // 10000 != 16:
                raise PersistenceError(
                    f"PostgreSQL 16 is required; server_version_num={server_version}"
                )
            postgis_version = connection.execute(
                text(
                    "SELECT COALESCE("
                    "(SELECT extversion FROM pg_extension WHERE extname = 'postgis'), "
                    "(SELECT default_version FROM pg_available_extensions "
                    "WHERE name = 'postgis'))"
                )
            ).scalar_one_or_none()
            if not str(postgis_version).startswith("3.4."):
                raise PersistenceError(
                    f"PostGIS 3.4 is required; found {postgis_version}"
                )
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = :table"
                    ),
                    {"schema": STAGING_SCHEMA, "table": TARGET_TABLE_NAME},
                ).scalars()
            )
    except PersistenceError:
        raise
    except SQLAlchemyError as exc:
        raise PersistenceError(
            "Could not verify PostgreSQL 16/PostGIS 3.4 and the staging target. "
            f"Confirm the database and run sql/schema.sql: {exc}"
        ) from exc

    expected_columns = set(target_table.columns.keys())
    missing_columns = expected_columns - columns
    if missing_columns:
        raise PersistenceError(
            f"{STAGING_SCHEMA}.{TARGET_TABLE_NAME} is missing candidate DDL columns: "
            f"{', '.join(sorted(missing_columns))}. Confirm the target DDL before loading."
        )


def _observation_values(row: Observation) -> dict[str, object]:
    return {
        "source_table_code": row.source_table_code,
        "county_key": row.county_key,
        "observation_year": row.observation_year,
        "county_name": row.county_name,
        "registrations": row.registrations,
        "deregistrations": row.deregistrations,
        "unit": row.unit,
        "source_url": row.source_url,
        "source_updated_at": row.source_updated_at,
        "source_retrieved_at": row.source_retrieved_at,
    }
