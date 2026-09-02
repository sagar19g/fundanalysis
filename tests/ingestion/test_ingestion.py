from pathlib import Path
import pandas as pd
import pytest
from sqlalchemy import text

from src.core.db_client import DatabaseClient
from src.core.exceptions import DataIngestionValidationError
from src.repositories.ingestion_repo import IngestionRepository
from src.services.ingestion import DataIngestionService


@pytest.fixture
def db_client(tmp_path: Path) -> DatabaseClient:
    db_file = tmp_path / "test_ingestion.db"
    client = DatabaseClient(database_url=f"sqlite:///{db_file}")

    # Set up base schema without optional audit columns to test dynamic migration
    with client.get_connection() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE fund_positions (
                fund_name TEXT,
                report_date TEXT,
                financial_type TEXT,
                symbol TEXT,
                security_name TEXT,
                price REAL,
                quantity REAL,
                realised_pl REAL,
                market_value REAL
            );
        """
            )
        )
    return client


@pytest.fixture
def ingestion_service(db_client: DatabaseClient) -> DataIngestionService:
    repo = IngestionRepository(db_client=db_client)
    return DataIngestionService(repository=repo)


# ==============================================================================
# 1. UNIT TESTS: Fund Name & Date Parsing
# ==============================================================================


@pytest.mark.parametrize(
    "input_name, expected_output",
    [
        ("Whitestone", "Whitestone"),
        ("rpt_whitestone_eom", "Whitestone"),
        ("WALLINGTON_2023_08", "Wallington"),
        ("Applebead.08.2023", "Applebead"),
        ("Unknown_Fund_ABC", "Unknown_Fund_ABC"),
    ],
)
def test_normalize_fund_name(
    ingestion_service: DataIngestionService, input_name: str, expected_output: str
):
    assert ingestion_service.normalize_fund_name(input_name) == expected_output


@pytest.mark.parametrize(
    "datestring, expected_date",
    [
        ("Whitestone_2023-08-31.csv", "2023-08-31"),
        ("report_08/31/2023.csv", "2023-08-31"),
        ("31-01-2023_report", "2023-01-31"),
    ],
)
def test_extract_eom_date_valid(
    ingestion_service: DataIngestionService, datestring: str, expected_date: str
):
    assert ingestion_service.extract_eom_date(datestring) == expected_date


def test_extract_eom_date_invalid_raises_validation_error(
    ingestion_service: DataIngestionService,
):
    with pytest.raises(DataIngestionValidationError):
        ingestion_service.extract_eom_date("invalid_file_no_date.csv")


# ==============================================================================
# 2. INTEGRATION TESTS: File Parsing, Validation & Idempotency
# ==============================================================================


def test_process_and_ingest_file_success_with_schema_migration(
    ingestion_service: DataIngestionService,
    db_client: DatabaseClient,
    tmp_path: Path,
):
    csv_path = tmp_path / "Whitestone.2023-08-31.csv"
    data = {
        "FINANCIAL TYPE": ["Equities"],
        "SYMBOL": ["AAPL"],
        "SECURITY NAME": ["Apple Inc"],
        "PRICE": [150.0],
        "QUANTITY": [100],
        "REALISED P/L": [10.5],
        "MARKET VALUE": [15000.0],
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)

    rows = ingestion_service.process_and_ingest_file(csv_path)
    assert rows == 1

    with db_client.get_connection() as conn:
        df_db = pd.read_sql_query("SELECT * FROM fund_positions", conn)

    assert len(df_db) == 1
    assert df_db.iloc[0]["fund_name"] == "Whitestone"
    assert df_db.iloc[0]["report_date"] == "2023-08-31"
    assert df_db.iloc[0]["source_file_name"] == "Whitestone.2023-08-31.csv"
    assert "created_at" in df_db.columns


def test_ingestion_idempotency_prevents_duplicate_records(
    ingestion_service: DataIngestionService,
    db_client: DatabaseClient,
    tmp_path: Path,
):
    csv_path = tmp_path / "Whitestone.2023-08-31.csv"
    data = {
        "FINANCIAL TYPE": ["Equities"],
        "SYMBOL": ["AAPL"],
        "SECURITY NAME": ["Apple Inc"],
        "PRICE": [150.0],
        "QUANTITY": [100],
        "REALISED P/L": [10.5],
        "MARKET VALUE": [15000.0],
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)

    # Ingest file twice
    ingestion_service.process_and_ingest_file(csv_path)
    ingestion_service.process_and_ingest_file(csv_path)

    with db_client.get_connection() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM fund_positions")
        ).scalar()

    # Idempotent partition deletion prevents row duplication
    assert count == 1


def test_process_file_missing_mandatory_headers_raises_validation_error(
    ingestion_service: DataIngestionService, tmp_path: Path
):
    bad_csv = tmp_path / "bad_report.2023-08-31.csv"
    pd.DataFrame({"SYMBOL": ["AAPL"], "PRICE": [150.0]}).to_csv(
        bad_csv, index=False
    )

    with pytest.raises(DataIngestionValidationError):
        ingestion_service.process_and_ingest_file(bad_csv)