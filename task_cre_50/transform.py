from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from task_cre_50.client import GenesisPayload, SOURCE_TABLE_URL, TABLE_CODE

REGISTRATIONS_CONTENT = "GEW011$QMU"
DEREGISTRATIONS_CONTENT = "GEW013$QMU"
COUNTY_KEY_PATTERN = re.compile(r"^[0-9]{5}$")
YEAR_PATTERN = re.compile(r"^[0-9]{4}$")
MISSING_MARKERS = {"", ".", "..", "..."}


class SourceDataError(ValueError):
    """Raised when the source response does not match the documented data shape."""


@dataclass(frozen=True)
class Observation:
    county_key: str
    county_name: str
    observation_year: int
    registrations: int | None
    deregistrations: int | None
    unit: str
    source_table_code: str
    source_url: str
    source_updated_at: datetime | None
    source_retrieved_at: datetime


def parse_payload(
    payload: GenesisPayload,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    retrieved_at: datetime | None = None,
) -> list[Observation]:
    if start_year is not None and end_year is not None and start_year > end_year:
        raise SourceDataError("start_year must be less than or equal to end_year")

    structure = payload.structure
    data_payload = payload.data
    table = structure.get("table")
    if not isinstance(table, dict) or table.get("code") != TABLE_CODE:
        raise SourceDataError(f"Expected GENESIS table {TABLE_CODE}")

    variables = structure.get("variables")
    contents = structure.get("contents")
    variable_values = structure.get("variableValues")
    if not isinstance(variables, dict) or not isinstance(contents, dict):
        raise SourceDataError("GENESIS table structure is missing variables or contents")
    if not isinstance(variable_values, dict):
        raise SourceDataError("GENESIS table structure has no regional key labels")
    for variable in ("KREISE", "JAHR"):
        if variable not in variables:
            raise SourceDataError(f"GENESIS table is missing dimension {variable}")

    _validate_unit(contents, "GEW011")
    _validate_unit(contents, "GEW013")
    source_updated_at = _parse_source_timestamp(table.get("lastChange"))
    retrieval_time = retrieved_at or datetime.now(timezone.utc)
    if retrieval_time.tzinfo is None:
        raise SourceDataError("retrieved_at must include a timezone")

    cubes = data_payload.get("data")
    if not isinstance(cubes, list):
        raise SourceDataError("GENESIS data response must include a data array")
    cube = _find_county_cube(cubes)
    dimension_indexes = _dimension_indexes(cube)
    dimension_codes = {
        name: {index: code for code, index in indexes.items()}
        for name, indexes in dimension_indexes.items()
    }
    dimensions = cube["id"]
    sizes = cube["size"]
    content_codes = dimension_indexes["content"]
    years = _selected_years(
        dimension_indexes["JAHR"],
        start_year=start_year,
        end_year=end_year,
    )
    county_names = _county_names(dimension_indexes["KREISE"], variable_values)
    if not county_names:
        raise SourceDataError("GENESIS response contains no five-digit county keys")

    cells: dict[tuple[str, int, str], int | None] = {}
    values = cube.get("value")
    expected_length = 1
    for size in sizes:
        expected_length *= size
    if not isinstance(values, list) or len(values) != expected_length:
        raise SourceDataError(
            f"GENESIS cube value count does not match dimensions: "
            f"expected {expected_length}"
        )

    strides = _strides(sizes)
    for flat_index, raw_value in enumerate(values):
        coordinates = [
            (flat_index // stride) % size
            for stride, size in zip(strides, sizes, strict=True)
        ]
        coordinate_by_dimension = dict(zip(dimensions, coordinates, strict=True))
        county_code = _code_for_index(
            dimension_codes["KREISE"], coordinate_by_dimension["KREISE"]
        )
        if county_code not in county_names:
            continue
        year_code = _code_for_index(
            dimension_codes["JAHR"], coordinate_by_dimension["JAHR"]
        )
        year = int(year_code)
        if year not in years:
            continue
        content_code = _code_for_index(
            dimension_codes["content"], coordinate_by_dimension["content"]
        )
        if content_code not in (REGISTRATIONS_CONTENT, DEREGISTRATIONS_CONTENT):
            continue
        key = (county_code, year, content_code)
        if key in cells:
            raise SourceDataError(f"Duplicate GENESIS observation cell: {key}")
        cells[key] = _parse_count(raw_value, key)

    expected_cells = len(county_names) * len(years) * 2
    if len(cells) != expected_cells:
        raise SourceDataError(
            f"GENESIS cube is incomplete: expected {expected_cells} county/year/"
            f"measure cells, received {len(cells)}"
        )

    rows = [
        Observation(
            county_key=county_key,
            county_name=county_names[county_key],
            observation_year=year,
            registrations=cells[(county_key, year, REGISTRATIONS_CONTENT)],
            deregistrations=cells[(county_key, year, DEREGISTRATIONS_CONTENT)],
            unit="Anzahl",
            source_table_code=TABLE_CODE,
            source_url=SOURCE_TABLE_URL,
            source_updated_at=source_updated_at,
            source_retrieved_at=retrieval_time,
        )
        for year in years
        for county_key in sorted(county_names)
    ]
    if not rows:
        raise SourceDataError("The requested year range returned no county records")
    return rows


def _validate_unit(contents: dict[str, Any], measure: str) -> None:
    measure_info = contents.get(measure)
    functions = measure_info.get("functions") if isinstance(measure_info, dict) else None
    quantity = functions.get("QMU") if isinstance(functions, dict) else None
    unit = quantity.get("label", {}).get("de") if isinstance(quantity, dict) else None
    if unit != "Anzahl":
        raise SourceDataError(
            f"Unexpected unit for {measure}: expected 'Anzahl', got {unit!r}"
        )


def _parse_source_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceDataError("GENESIS lastChange must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceDataError(f"Invalid GENESIS lastChange timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SourceDataError("GENESIS lastChange timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _find_county_cube(cubes: list[Any]) -> dict[str, Any]:
    matching = []
    for cube in cubes:
        if not isinstance(cube, dict):
            continue
        dimensions = cube.get("id")
        if not isinstance(dimensions, list):
            continue
        dimension_data = cube.get("dimension")
        if not isinstance(dimension_data, dict):
            continue
        content_dimension = dimension_data.get("content")
        category = (
            content_dimension.get("category")
            if isinstance(content_dimension, dict)
            else None
        )
        content = category.get("index") if isinstance(category, dict) else None
        if (
            all(name in dimensions for name in ("content", "JAHR", "KREISE"))
            and isinstance(content, dict)
            and REGISTRATIONS_CONTENT in content
            and DEREGISTRATIONS_CONTENT in content
        ):
            matching.append(cube)
    if len(matching) != 1:
        raise SourceDataError(
            "Expected exactly one county cube containing registrations and "
            f"deregistrations; found {len(matching)}"
        )
    return matching[0]


def _dimension_indexes(cube: dict[str, Any]) -> dict[str, dict[str, int]]:
    dimensions = cube.get("id")
    sizes = cube.get("size")
    raw_dimensions = cube.get("dimension")
    if (
        not isinstance(dimensions, list)
        or not isinstance(sizes, list)
        or len(dimensions) != len(sizes)
        or len(set(dimensions)) != len(dimensions)
        or not isinstance(raw_dimensions, dict)
    ):
        raise SourceDataError("GENESIS cube has invalid dimension metadata")

    indexes: dict[str, dict[str, int]] = {}
    for name, size in zip(dimensions, sizes, strict=True):
        if not isinstance(size, int) or size <= 0:
            raise SourceDataError(f"GENESIS dimension {name} has invalid size")
        dimension = raw_dimensions.get(name)
        category = dimension.get("category") if isinstance(dimension, dict) else None
        category_indexes = (
            category.get("index") if isinstance(category, dict) else None
        )
        if not isinstance(category_indexes, dict):
            raise SourceDataError(f"GENESIS dimension {name} has no category index")
        inverted: dict[int, str] = {}
        for code, index in category_indexes.items():
            if not isinstance(index, int) or index < 0 or index >= size:
                raise SourceDataError(
                    f"GENESIS dimension {name} has an invalid index for {code}"
                )
            if index in inverted:
                raise SourceDataError(
                    f"GENESIS dimension {name} has duplicate category indexes"
                )
            inverted[index] = str(code)
        if len(inverted) != size:
            raise SourceDataError(
                f"GENESIS dimension {name} has {len(inverted)} categories, "
                f"expected {size}"
            )
        indexes[name] = {code: index for index, code in inverted.items()}

    required = {"content", "JAHR", "KREISE"}
    if not required.issubset(indexes):
        raise SourceDataError("GENESIS county cube is missing required dimensions")
    for name, size in zip(dimensions, sizes, strict=True):
        if name not in required and size != 1:
            raise SourceDataError(
                f"GENESIS cube has unsupported non-singleton dimension {name}"
            )
    return indexes


def _selected_years(
    year_indexes: dict[str, int],
    *,
    start_year: int | None,
    end_year: int | None,
) -> list[int]:
    years = []
    for code in year_indexes:
        if not YEAR_PATTERN.fullmatch(code):
            raise SourceDataError(f"Invalid observation year in GENESIS data: {code}")
        year = int(code)
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        years.append(year)
    if not years:
        raise SourceDataError("The requested year range is not present in GENESIS data")
    return sorted(years)


def _county_names(
    county_indexes: dict[str, int],
    variable_values: dict[str, Any],
) -> dict[str, str]:
    names: dict[str, str] = {}
    for code in county_indexes:
        if not COUNTY_KEY_PATTERN.fullmatch(code):
            continue
        metadata = variable_values.get(code)
        label = metadata.get("label") if isinstance(metadata, dict) else None
        name = label.get("de") if isinstance(label, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise SourceDataError(f"Missing official county name for key {code}")
        names[code] = name.strip()
    return names


def _code_for_index(codes_by_index: dict[int, str], index: int) -> str:
    try:
        return codes_by_index[index]
    except KeyError as exc:
        raise SourceDataError(
            f"No GENESIS code exists for dimension index {index}"
        ) from exc


def _parse_count(value: Any, key: tuple[str, int, str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in MISSING_MARKERS:
            return None
    if isinstance(value, bool):
        raise SourceDataError(f"Boolean is not a valid count for {key}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SourceDataError(f"Invalid count value {value!r} for {key}") from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise SourceDataError(f"Count must be a non-negative integer for {key}")
    return int(number)


def _strides(sizes: list[int]) -> list[int]:
    strides = []
    for position in range(len(sizes)):
        stride = 1
        for size in sizes[position + 1 :]:
            stride *= size
        strides.append(stride)
    return strides
