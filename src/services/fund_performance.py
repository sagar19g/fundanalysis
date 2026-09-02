import logging
from pathlib import Path
import pandas as pd
from src.repositories.performance_repo import AbstractPerformanceRepository
from src.core.exceptions import EmptyPerformanceResultsError

logger = logging.getLogger(__name__)


class FundPerformanceService:
    """Domain service orchestrating Rate of Return analysis and exports."""

    def __init__(self, repository: AbstractPerformanceRepository):
        self.repository = repository

    def run_performance_analysis(self, output_path: Path) -> pd.DataFrame:
        """Fetches monthly performance metrics, validates results, and writes CSV output."""
        logger.info("Starting best-performing fund analysis...")
        df_rankings = self.repository.fetch_monthly_performance_rankings()

        if df_rankings.empty:
            raise EmptyPerformanceResultsError(
                "Performance query executed successfully but returned 0 rows. "
                "Ensure position baseline records exist across multiple months."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        df_rankings.to_csv(output_path, index=False)
        logger.info(
            f"Performance analysis complete. Generated {len(df_rankings)} monthly records at {output_path.resolve()}"
        )

        return df_rankings