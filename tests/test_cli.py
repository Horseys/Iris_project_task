import json
from pathlib import Path

from task_cre_50.cli import main

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "genesis_regional_sample.json"


def test_fixture_smoke_run_reports_processed_and_missing_counts(capsys) -> None:
    exit_code = main(
        [
            "--input-json",
            str(FIXTURE_PATH),
            "--start-year",
            "2024",
            "--end-year",
            "2024",
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 0
    assert result["processed_count"] == 2
    assert result["inserted_count"] == 0
    assert result["updated_count"] == 0
    assert result["missing_value_rows"] == 1
    assert result["failed_count"] == 0
    assert result["database_loaded"] is False


def test_load_db_requires_db_uri(capsys, caplog, monkeypatch) -> None:
    monkeypatch.delenv("DB_URI", raising=False)
    exit_code = main(["--input-json", str(FIXTURE_PATH), "--load-db"])

    capsys.readouterr()
    assert exit_code == 1
    assert "DB_URI is required" in caplog.text
    assert "processed_count=4" in caplog.text
    assert "failed_count=4" in caplog.text
