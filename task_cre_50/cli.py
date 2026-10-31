from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from task_cre_50.client import (
    DEFAULT_BASE_URL,
    GenesisAPIError,
    GenesisPayload,
    GenesisRegionalClient,
)
from task_cre_50.storage import PersistenceError, load_observations
from task_cre_50.transform import Observation, SourceDataError, parse_payload

LOGGER = logging.getLogger("task_cre_50")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="task-cre-50",
        description=(
            "Ingest Destatis GENESIS Regional county business registrations and "
            "deregistrations."
        ),
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Read a saved {structure, data} GENESIS response instead of the API.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="GENESIS Regional service root (default: %(default)s).",
    )
    parser.add_argument("--start-year", type=int, help="Inclusive first year.")
    parser.add_argument("--end-year", type=int, help="Inclusive last year.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="HTTP timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--load-db",
        action="store_true",
        help=(
            "Upsert into iris_staging.socio_demographics_staging. "
            "Requires DB_URI and the candidate DDL."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    args = build_parser().parse_args(argv)
    processed_count = 0
    missing_value_count = 0
    inserted_count = 0
    updated_count = 0

    try:
        payload = (
            _read_fixture(args.input_json)
            if args.input_json
            else GenesisRegionalClient(
                base_url=args.base_url,
                timeout_seconds=args.timeout,
            ).fetch_payload()
        )
        rows = parse_payload(
            payload,
            start_year=args.start_year,
            end_year=args.end_year,
        )
        processed_count = len(rows)
        missing_value_count = sum(
            row.registrations is None or row.deregistrations is None
            for row in rows
        )

        if args.load_db:
            result = load_observations(os.getenv("DB_URI", ""), rows)
            inserted_count = result.inserted_count
            updated_count = result.updated_count
    except (
        GenesisAPIError,
        SourceDataError,
        PersistenceError,
        OSError,
        ValueError,
    ) as exc:
        failed_count = processed_count or 1
        LOGGER.error(
            "ETL failed: processed_count=%d inserted_count=%d updated_count=%d "
            "failed_count=%d error=%s",
            processed_count,
            inserted_count,
            updated_count,
            failed_count,
            exc,
            exc_info=True,
        )
        return 1

    summary = {
        "source_table_code": "52311-01-04-4",
        "processed_count": processed_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "missing_value_rows": missing_value_count,
        "failed_count": 0,
        "database_loaded": args.load_db,
    }
    LOGGER.info(
        "ETL completed: processed_count=%d inserted_count=%d updated_count=%d "
        "failed_count=0 missing_value_rows=%d",
        processed_count,
        inserted_count,
        updated_count,
        missing_value_count,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _read_fixture(path: Path) -> GenesisPayload:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceDataError(f"Fixture is not valid JSON: {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise SourceDataError("Fixture root must be a JSON object")
    structure = document.get("structure")
    data = document.get("data")
    if not isinstance(structure, dict) or not isinstance(data, dict):
        raise SourceDataError("Fixture must contain object properties 'structure' and 'data'")
    return GenesisPayload(structure=structure, data=data)
