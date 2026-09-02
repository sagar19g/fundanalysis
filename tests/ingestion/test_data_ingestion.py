import sqlite3
from pathlib import Path
import pandas as pd
import pytest

from src.ingestion.data_ingestion import (
    extract_eom_date,
    ingest_fund_csv,
    normalize_fund_name,
    populate_fund_data,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture providing a temporary SQLite database path."""
    return tmp_path / "test_reference_data.db"


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Fixture providing a mock fund CSV report with whitespace and extra headers."""
    csv_path = tmp_path / "Whitestone.2023-08-31.csv"
    data = {
        "FINANCIAL TYPE ": [" Equities ", "Government Bond"],
        "SYMBOL": ["AAPL", "US12345"],
        "SECURITY NAME": ["Apple Inc", "US Treasury"],
        "SEDOL": ["B00001", "B00002"],
        "PRICE": [150.0, 99.5],
        "QUANTITY": [100, 500],
        "REALISED P/L": [10.5, 0.0],
        "MARKET VALUE": [15000.0, 49750.0],
        "EXTRA_HEADER": ["IGNORE_1", "IGNORE_2"],
    }
    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    return csv_path


# ==============================================================================
# 1. UNIT TESTS: normalize_fund_name
# ==============================================================================

@pytest.mark.parametrize(
    "input_name, expected_output",
    [
        ("Whitestone", "Whitestone"),
        ("rpt_whitestone_eom", "Whitestone"),
        ("WALLINGTON_2023_08", "Wallington"),
        ("catalysm-fund-report", "Catalysm"),
        ("Belaware_fund", "Belaware"),
        ("gohen", "Gohen"),
        ("Applebead.08.2023", "Applebead"),
        ("Magnum_Global", "Magnum"),
        ("trustmind_inc", "Trustmind"),
        ("Leeder_Cap", "Leeder"),
        ("Virtous_Holdings", "Virtous"),
        ("Unknown_Fund_ABC", "Unknown_Fund_ABC"),  # Unmatched fallback
        ("   Spaced_Fund   ", "Spaced_Fund"),  # Whitespace strip fallback
    ],
)
def test_normalize_fund_name(input_name: str, expected_output: str):
    """Tests exact, case-insensitive, substring, and fallback fund name normalization."""
    assert normalize_fund_name(input_name) == expected_output


# ==============================================================================
# 2. UNIT TESTS: extract_eom_date
# ==============================================================================

@pytest.mark.parametrize(
    "datestring, expected_date",
    [
        ("Whitestone_2023-08-31.csv", "2023-08-31"),
        ("report_08/31/2023.csv", "2023-08-31"),
        ("Fund_2023.12.31_final.csv", "2023-12-31"),
        ("20230531_fund_data.csv", "2023-05-31"),
        ("2023-02-28", "2023-02-28"),
        ("31-01-2023_report", "2023-01-31"),
    ],
)
def test_extract_eom_date_valid(datestring: str, expected_date: str):
    """Tests flexible regex extraction and YYYY-MM-DD formatting across date patterns."""
    assert extract_eom_date(datestring) == expected_date


def test_extract_eom_date_invalid_throws_exception():
    """Verifies exception is raised when no parseable date exists in input string."""
    with pytest.raises(Exception):
        extract_eom_date("invalid_file_no_date_here.csv")


# ==============================================================================
# 3. UNIT TESTS: ingest_fund_csv
# ==============================================================================

def test_ingest_fund_csv_success(temp_db: Path, sample_csv: Path):
    """Tests column header cleaning, mapping, metadata injection, and database insertion."""
    rows = ingest_fund_csv(
        db_path=str(temp_db),
        csv_path=str(sample_csv),
        fund_name="Whitestone",
        report_date="2023-08-31",
    )

    assert rows == 2

    conn = sqlite3.connect(temp_db)
    df_db = pd.read_sql_query("SELECT * FROM fund_positions", conn)
    conn.close()

    assert len(df_db) == 2
    assert list(df_db.columns) == [
        "fund_name",
        "report_date",
        "financial_type",
        "symbol",
        "security_name",
        "price",
        "quantity",
        "realised_pl",
        "market_value",
    ]
    assert df_db.iloc[0]["fund_name"] == "Whitestone"
    assert df_db.iloc[0]["report_date"] == "2023-08-31"
    assert df_db.iloc[0]["financial_type"] == " Equities "


def test_ingest_fund_csv_missing_columns_raises_key_error(
    temp_db: Path, tmp_path: Path
):
    """Ensures KeyError is raised if required financial headers are missing from CSV."""
    bad_csv = tmp_path / "bad_report.csv"
    pd.DataFrame({"SYMBOL": ["AAPL"], "PRICE": [150.0]}).to_csv(
        bad_csv, index=False
    )

    with pytest.raises(KeyError):
        ingest_fund_csv(
            db_path=str(temp_db),
            csv_path=str(bad_csv),
            fund_name="Whitestone",
            report_date="2023-08-31",
        )


# ==============================================================================
# 4. UNIT TESTS: populate_fund_data
# ==============================================================================

def test_populate_fund_data_directory_not_found(
    temp_db: Path, capsys: pytest.CaptureFixture
):
    """Verifies graceful return when the target CSV folder does not exist."""
    populate_fund_data(str(temp_db), "non_existent_folder_path")
    captured = capsys.readouterr()
    assert "Directory non_existent_folder_path does not exist." in captured.out


def test_populate_fund_data_successful_directory_ingestion(
    temp_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture
):
    """Tests end-to-end processing and ingestion of multiple CSV files in a directory."""
    data_dir = tmp_path / "external-funds"
    data_dir.mkdir()

    file1 = data_dir / "whitestone.report.2023-08-31.csv"
    file2 = data_dir / "catalysm_eom.2023-09-30.csv"

    mock_data = {
        "FINANCIAL TYPE": ["Equities"],
        "SYMBOL": ["AAPL"],
        "SECURITY NAME": ["Apple"],
        "PRICE": [150.0],
        "QUANTITY": [10],
        "REALISED P/L": [0.0],
        "MARKET VALUE": [1500.0],
    }

    pd.DataFrame(mock_data).to_csv(file1, index=False)
    pd.DataFrame(mock_data).to_csv(file2, index=False)

    populate_fund_data(str(temp_db), str(data_dir))

    captured = capsys.readouterr()
    assert "Inserted 1 rows for 'Whitestone'" in captured.out
    assert "Inserted 1 rows for 'Catalysm'" in captured.out

    conn = sqlite3.connect(temp_db)
    count = pd.read_sql_query(
        "SELECT COUNT(*) as cnt FROM fund_positions", conn
    ).iloc[0]["cnt"]
    conn.close()

    assert count == 2


def test_populate_fund_data_handles_corrupted_csv(
    temp_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture
):
    """Ensures execution continues gracefully when encountering a corrupted CSV file."""
    data_dir = tmp_path / "external-funds"
    data_dir.mkdir()

    bad_file = data_dir / "corrupted_file.2023-08-31.csv"
    bad_file.write_text("NOT_VALID_CSV_CONTENT_XXXXX")

    populate_fund_data(str(temp_db), str(data_dir))

    captured = capsys.readouterr()
    assert "Error processing file corrupted_file.2023-08-31.csv" in captured.out