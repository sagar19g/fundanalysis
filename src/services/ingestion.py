from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from dateutil import parser
import pandas as pd

from config.settings import config
from src.core.exceptions import DataIngestionValidationError
from src.repositories.ingestion_repo import IngestionRepository

logger = logging.getLogger(__name__)


class DataIngestionService:
    """Domain service orchestrating file parsing, validation, and ingestion."""

    # Mandatory input headers required across all fund report CSVs
    REQUIRED_INPUT_HEADERS = {
        "FINANCIAL TYPE",
        "SYMBOL",
        "SECURITY NAME",
        "PRICE",
        "QUANTITY",
        "REALISED P/L",
        "MARKET VALUE",
    }

    COLUMN_MAPPING = {
        "FINANCIAL TYPE": "financial_type",
        "SYMBOL": "symbol",
        "SECURITY NAME": "security_name",
        "SEDOL": "sedol",
        "PRICE": "price",
        "QUANTITY": "quantity",
        "REALISED P/L": "realised_pl",
        "MARKET VALUE": "market_value",
    }

    REQUIRED_COLS = [
        "fund_name",
        "report_date",
        "financial_type",
        "symbol",
        "security_name",
        "sedol",
        "price",
        "quantity",
        "realised_pl",
        "market_value",
        "created_at",
        "source_file_name",
    ]

    def __init__(self, repository: IngestionRepository):
        self.repository = repository

    def normalize_fund_name(self, raw_name: str) -> str:
        for fund in config.known_funds:
            if fund.lower() in raw_name.lower():
                return fund
        return raw_name.strip()

    def extract_eom_date(self, datestring: str) -> str:
        date_match = re.search(
            r"\b(\d{4}[-/_.]\d{1,2}[-/_.]\d{1,2}|\d{1,2}[-/_.]\d{1,2}[-/_.]\d{4}|\d{8})\b",
            datestring,
        )
        date_str = date_match.group(1) if date_match else datestring
        try:
            parsed_dt = parser.parse(date_str, fuzzy=True, dayfirst=False)
            return parsed_dt.strftime("%Y-%m-%d")
        except Exception as e:
            raise DataIngestionValidationError(
                f"Failed to parse date from string '{datestring}': {e}"
            ) from e

    def process_and_ingest_file(self, csv_path: Path) -> int:
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            raise DataIngestionValidationError(f"Invalid CSV file {csv_path.name}: {e}")

        df.columns = df.columns.str.strip()

        # Validate mandatory input headers only
        missing_headers = self.REQUIRED_INPUT_HEADERS - set(df.columns)
        if missing_headers:
            raise DataIngestionValidationError(
                f"File '{csv_path.name}' is missing required headers: {missing_headers}"
            )

        df.rename(columns=self.COLUMN_MAPPING, inplace=True)

        # Ensure optional sedol column exists
        if "sedol" not in df.columns:
            df["sedol"] = None

        raw_fund_name = csv_path.stem.split(".")[0]
        fund_name = self.normalize_fund_name(raw_fund_name)
        report_date = self.extract_eom_date(csv_path.name)

        df["fund_name"] = fund_name
        df["report_date"] = report_date
        df["created_at"] = datetime.now(timezone.utc).isoformat()
        df["source_file_name"] = csv_path.name

        df = df[self.REQUIRED_COLS]

        return self.repository.save_positions_idempotently(df, fund_name, report_date)

    def ingest_directory(self, data_dir: Path) -> int:
        if not data_dir.exists():
            raise FileNotFoundError(f"Directory does not exist: {data_dir.resolve()}")

        total_rows = 0
        for csv_file in data_dir.glob("*.csv"):
            try:
                rows = self.process_and_ingest_file(csv_file)
                total_rows += rows
            except DataIngestionValidationError as ve:
                logger.error(f"Validation failed for {csv_file.name}: {ve}")
            except Exception as e:
                logger.error(f"Unexpected error processing {csv_file.name}: {e}")

        return total_rows