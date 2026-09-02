import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)


class PriceReconciliationService:
    """Domain service orchestrating price reconciliation logic."""

    def __init__(self, repository):
        self.repository = repository

    def run_reconciliation(self, output_path: Path) -> pd.DataFrame:
        df_results = self.repository.fetch_reconciliation_data()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        df_results.to_csv(output_path, index=False)
        logger.info(f"Reconciliation exported to {output_path.resolve()}")

        return df_results