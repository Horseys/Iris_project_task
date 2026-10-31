import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from task_cre_50.client import GenesisPayload
from task_cre_50.transform import SourceDataError, parse_payload

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "genesis_regional_sample.json"


def load_payload() -> GenesisPayload:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return GenesisPayload(
        structure=document["structure"],
        data=document["data"],
    )


def test_normalizes_county_keys_years_units_and_nulls() -> None:
    retrieved_at = datetime(2026, 10, 30, tzinfo=timezone.utc)
    rows = parse_payload(
        load_payload(),
        start_year=2024,
        end_year=2024,
        retrieved_at=retrieved_at,
    )

    assert [(row.county_key, row.county_name) for row in rows] == [
        ("01001", "Flensburg, kreisfreie Stadt"),
        ("09162", "München, kreisfreie Stadt"),
    ]
    assert [(row.registrations, row.deregistrations) for row in rows] == [
        (11, None),
        (21, 4),
    ]
    assert all(row.observation_year == 2024 for row in rows)
    assert all(row.unit == "Anzahl" for row in rows)
    assert all(row.source_table_code == "52311-01-04-4" for row in rows)
    assert all(row.source_retrieved_at == retrieved_at for row in rows)
    assert all(row.source_updated_at is not None for row in rows)


def test_selects_all_years_and_does_not_conflate_subcounty_keys() -> None:
    rows = parse_payload(load_payload())

    assert len(rows) == 4
    assert {row.observation_year for row in rows} == {2023, 2024}
    assert all(len(row.county_key) == 5 for row in rows)
    assert not any(row.county_key == "11007007" for row in rows)


def test_rejects_nonmatching_table_code() -> None:
    payload = load_payload()
    payload.structure["table"]["code"] = "52311-0150"

    with pytest.raises(SourceDataError, match="Expected GENESIS table"):
        parse_payload(payload)


def test_rejects_unknown_measure_unit() -> None:
    payload = load_payload()
    payload.structure["contents"]["GEW011"]["functions"]["QMU"]["label"]["de"] = (
        "Prozent"
    )

    with pytest.raises(SourceDataError, match="Unexpected unit"):
        parse_payload(payload)


def test_rejects_invalid_count_instead_of_coercing_it() -> None:
    payload = load_payload()
    payload.data["data"][0]["value"][0] = 1.5

    with pytest.raises(SourceDataError, match="non-negative integer"):
        parse_payload(payload)


def test_rejects_year_ranges_not_present_in_source() -> None:
    with pytest.raises(SourceDataError, match="not present"):
        parse_payload(load_payload(), start_year=2030, end_year=2030)
