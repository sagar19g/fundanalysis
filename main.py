import argparse
import logging
import sys

from config.settings import config
from src.core.db_client import DatabaseClient
from src.repositories.ingestion_repo import IngestionRepository
from src.repositories.performance_repo import SQLitePerformanceRepository
from src.repositories.reconciliation_repo import SQLiteReconciliationRepository
from src.services.fund_performance import FundPerformanceService
from src.services.ingestion import DataIngestionService
from src.services.reconciliation import PriceReconciliationService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
)
logger = logging.getLogger("FinancialPipeline")


def run_ingestion(db_client: DatabaseClient) -> None:
    logger.info("Initializing Data Ingestion task...")
    repository = IngestionRepository(db_client=db_client)
    service = DataIngestionService(repository=repository)
    service.ingest_directory(data_dir=config.raw_data_dir)


def run_reconciliation(db_client: DatabaseClient) -> None:
    logger.info("Initializing Price Reconciliation task...")
    repository = SQLiteReconciliationRepository(
        db_client=db_client, sql_dir=config.sql_dir
    )
    service = PriceReconciliationService(repository=repository)
    service.run_reconciliation(output_path=config.output_dir / "price_reconciliation.csv")


def run_performance(db_client: DatabaseClient) -> None:
    logger.info("Initializing Fund Performance task...")
    repository = SQLitePerformanceRepository(
        db_client=db_client, sql_dir=config.sql_dir
    )
    service = FundPerformanceService(repository=repository)
    service.run_performance_analysis(
        output_path=config.output_dir / "best_performing_funds.csv"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Financial Data & Analytics Pipeline Engine"
    )
    parser.add_argument(
        "--task",
        type=str,
        choices=["ingestion", "reconciliation", "performance", "all"],
        default="all",
        help="Pipeline task to run (default: 'all')",
    )

    args = parser.parse_args()

    # Instantiate DatabaseClient using the dynamic database_url settings property
    db_client = DatabaseClient(database_url=config.database_url)

    try:
        if args.task in ("ingestion", "all"):
            run_ingestion(db_client)

        if args.task in ("reconciliation", "all"):
            run_reconciliation(db_client)

        if args.task in ("performance", "all"):
            run_performance(db_client)

        logger.info("Pipeline execution completed successfully.")

    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()