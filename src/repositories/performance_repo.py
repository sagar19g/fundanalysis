from abc import ABC, abstractmethod
import logging
from pathlib import Path
import pandas as pd
from src.core.db_client import DatabaseClient
from src.core.exceptions import SQLQueryExecutionError

logger = logging.getLogger(__name__)


class AbstractPerformanceRepository(ABC):
    """Interface contract for fund performance data access."""

    @abstractmethod
    def fetch_monthly_performance_rankings(self) -> pd.DataFrame:
        """Retrieves monthly fund Rate of Return (RoR) rankings."""
        pass


class SQLitePerformanceRepository(AbstractPerformanceRepository):
    """SQLite implementation of the performance data repository."""

    def __init__(self, db_client: DatabaseClient, sql_dir: Path):
        self.db_client = db_client
        self.sql_dir = sql_dir

    def fetch_monthly_performance_rankings(self) -> pd.DataFrame:
        sql_path = self.sql_dir / "monthly_fund_performance.sql"

        if not sql_path.exists():
            raise FileNotFoundError(
                f"SQL query file not found at: {sql_path.resolve()}"
            )

        query = sql_path.read_text(encoding="utf-8")

        try:
            with self.db_client.get_connection() as conn:
                logger.info("Executing monthly performance SQL query...")
                return pd.read_sql_query(query, conn)
        except Exception as e:
            raise SQLQueryExecutionError(
                f"Database query execution failed: {e}"
            ) from e