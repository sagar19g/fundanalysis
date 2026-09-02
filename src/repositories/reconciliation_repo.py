import logging
from pathlib import Path
import pandas as pd
from sqlalchemy import text, Connection

from src.core.db_client import DatabaseClient
from src.core.exceptions import SQLQueryExecutionError

logger = logging.getLogger(__name__)


class SQLiteReconciliationRepository:
    """Handles price reconciliation indexing and query execution via SQLAlchemy."""

    def __init__(self, db_client: DatabaseClient, sql_dir: Path):
        self.db_client = db_client
        self.sql_dir = sql_dir

    def prepare_indexes(self, conn: Connection) -> None:
        """Executes index preparation statements using standard SQLAlchemy execution."""
        logger.info("Building temporary normalized price tables and indexes...")

        statements = [
            "DROP TABLE IF EXISTS norm_eq_prices;",
            """
            CREATE TEMP TABLE norm_eq_prices AS
            SELECT 
                SYMBOL, 
                PRICE,
                CASE 
                    WHEN DATETIME LIKE '%-%' THEN DATETIME
                    WHEN DATETIME LIKE '%/%' THEN 
                        SUBSTR(DATETIME, -4) || '-' ||
                        PRINTF('%02d', CAST(SUBSTR(DATETIME, 1, INSTR(DATETIME, '/') - 1) AS INT)) || '-' ||
                        PRINTF('%02d', CAST(SUBSTR(DATETIME, INSTR(DATETIME, '/') + 1, INSTR(SUBSTR(DATETIME, INSTR(DATETIME, '/') + 1), '/') - 1) AS INT))
                    ELSE DATETIME
                END AS iso_ref_date
            FROM equity_prices;
            """,
            "CREATE INDEX IF NOT EXISTS idx_neq_sym_dt ON norm_eq_prices(SYMBOL, iso_ref_date DESC);",
            "DROP TABLE IF EXISTS norm_bd_prices;",
            """
            CREATE TEMP TABLE norm_bd_prices AS
            SELECT 
                ISIN, 
                PRICE,
                CASE 
                    WHEN DATETIME LIKE '%-%' THEN DATETIME
                    WHEN DATETIME LIKE '%/%' THEN 
                        SUBSTR(DATETIME, -4) || '-' ||
                        PRINTF('%02d', CAST(SUBSTR(DATETIME, 1, INSTR(DATETIME, '/') - 1) AS INT)) || '-' ||
                        PRINTF('%02d', CAST(SUBSTR(DATETIME, INSTR(DATETIME, '/') + 1, INSTR(SUBSTR(DATETIME, INSTR(DATETIME, '/') + 1), '/') - 1) AS INT))
                    ELSE DATETIME
                END AS iso_ref_date
            FROM bond_prices;
            """,
            "CREATE INDEX IF NOT EXISTS idx_nbd_isin_dt ON norm_bd_prices(ISIN, iso_ref_date DESC);"
        ]

        for stmt in statements:
            conn.execute(text(stmt))

    def fetch_reconciliation_data(self) -> pd.DataFrame:
        """Executes indexing and reconciliation query within a single SQLAlchemy connection."""
        sql_path = self.sql_dir / "price_reconciliation.sql"

        if not sql_path.exists():
            raise FileNotFoundError(
                f"SQL query file not found at: {sql_path.resolve()}"
            )

        query = sql_path.read_text(encoding="utf-8")

        try:
            with self.db_client.get_connection() as conn:
                self.prepare_indexes(conn)
                logger.info("Executing price reconciliation query...")
                return pd.read_sql_query(text(query), conn)
        except Exception as e:
            raise SQLQueryExecutionError(
                f"Reconciliation query execution failed: {e}"
            ) from e