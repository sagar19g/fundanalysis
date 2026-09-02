import logging
import pandas as pd
from sqlalchemy import text, Connection

from src.core.db_client import DatabaseClient
from src.core.exceptions import SQLQueryExecutionError

logger = logging.getLogger(__name__)


class IngestionRepository:
    """Handles atomic database operations for position data ingestion via SQLAlchemy."""

    def __init__(self, db_client: DatabaseClient):
        self.db_client = db_client

    def _ensure_schema(self, conn: Connection) -> None:
        """Executes lightweight schema migration to ensure audit columns exist."""
        table_info = conn.execute(text("PRAGMA table_info(fund_positions)")).fetchall()
        existing_columns = {row[1] for row in table_info}

        audit_columns = {
            "created_at": "TEXT",
            "source_file_name": "TEXT",
            "sedol": "TEXT",
        }

        for col_name, col_type in audit_columns.items():
            if col_name not in existing_columns:
                logger.info(f"Adding missing column '{col_name}' to 'fund_positions' table...")
                conn.execute(
                    text(f"ALTER TABLE fund_positions ADD COLUMN {col_name} {col_type}")
                )

    def save_positions_idempotently(
        self, df: pd.DataFrame, fund_name: str, report_date: str
    ) -> int:
        """Deletes existing entries for fund/date partition before writing new records."""
        try:
            with self.db_client.get_connection() as conn:
                # 1. Ensure table schema matches DataFrame columns
                self._ensure_schema(conn)

                # 2. Clear existing partition
                delete_stmt = text(
                    "DELETE FROM fund_positions WHERE fund_name = :fund_name AND report_date = :report_date"
                )
                result = conn.execute(
                    delete_stmt,
                    {"fund_name": fund_name, "report_date": report_date}
                )

                deleted_rows = result.rowcount
                if deleted_rows > 0:
                    logger.info(
                        f"Cleared {deleted_rows} existing records for '{fund_name}' on {report_date}."
                    )

                # 3. Insert new partition records
                df.to_sql("fund_positions", conn, if_exists="append", index=False)
                return len(df)
        except Exception as e:
            raise SQLQueryExecutionError(
                f"Failed to idempotently ingest positions for {fund_name}: {e}"
            ) from e