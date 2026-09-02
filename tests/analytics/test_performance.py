from pathlib import Path
import pytest
from sqlalchemy import text

from src.core.db_client import DatabaseClient
from src.core.exceptions import EmptyPerformanceResultsError
from src.repositories.performance_repo import SQLitePerformanceRepository
from src.services.fund_performance import FundPerformanceService


@pytest.fixture
def perf_setup(tmp_path: Path):
    db_path = tmp_path / "test_perf.db"
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)

    db_client = DatabaseClient(database_url=f"sqlite:///{db_path}")

    with db_client.get_connection() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE fund_positions (
                fund_name TEXT, report_date TEXT, realised_pl REAL, market_value REAL
            );
        """
            )
        )

    sql_file = sql_dir / "monthly_fund_performance.sql"
    sql_file.write_text(
        """
        WITH monthly_fund_totals AS (
            SELECT fund_name, report_date, SUM(market_value) AS fund_mv_end, SUM(realised_pl) AS fund_realized_pl
            FROM fund_positions GROUP BY fund_name, report_date
        ),
        monthly_ror AS (
            SELECT fund_name, report_date, fund_mv_end, fund_realized_pl,
            LAG(fund_mv_end) OVER (PARTITION BY fund_name ORDER BY report_date) AS fund_mv_start
            FROM monthly_fund_totals
        ),
        ror_calculated AS (
            SELECT fund_name, report_date, fund_mv_start, fund_mv_end, fund_realized_pl,
            (fund_mv_end - fund_mv_start + fund_realized_pl) / NULLIF(fund_mv_start, 0) AS rate_of_return
            FROM monthly_ror WHERE fund_mv_start IS NOT NULL
        ),
        ranked_funds AS (
            SELECT report_date, fund_name AS best_performing_fund, ROUND(fund_mv_start, 2) AS fund_mv_start, ROUND(fund_mv_end, 2) AS fund_mv_end,
            ROUND(fund_realized_pl, 2) AS realized_pl, ROUND(rate_of_return * 100, 4) AS ror_pct,
            ROW_NUMBER() OVER (PARTITION BY report_date ORDER BY rate_of_return DESC) AS rk
            FROM ror_calculated
        )
        SELECT report_date, best_performing_fund, fund_mv_start, fund_mv_end, realized_pl, ror_pct
        FROM ranked_funds WHERE rk = 1 ORDER BY report_date;
    """,
        encoding="utf-8",
    )

    repo = SQLitePerformanceRepository(db_client=db_client, sql_dir=sql_dir)
    service = FundPerformanceService(repository=repo)

    return {
        "db_client": db_client,
        "service": service,
        "output_dir": tmp_path / "output",
    }


def test_fund_performance_ror_calculation_and_ranking(perf_setup):
    db_client = perf_setup["db_client"]
    service = perf_setup["service"]

    with db_client.get_connection() as conn:
        # Combined into single multi-row INSERTs to comply with DBAPI constraints
        conn.execute(
            text(
                """
            INSERT INTO fund_positions VALUES 
                ('FundA', '2023-01-31', 0, 1000.0),
                ('FundB', '2023-01-31', 0, 2000.0),
                ('FundA', '2023-02-28', 100, 1200.0),
                ('FundB', '2023-02-28', 0, 2200.0);
        """
            )
        )

    out_csv = perf_setup["output_dir"] / "perf.csv"
    df = service.run_performance_analysis(output_path=out_csv)

    assert len(df) == 1
    feb = df.iloc[0]

    assert feb["report_date"] == "2023-02-28"
    assert feb["best_performing_fund"] == "FundA"
    assert feb["ror_pct"] == 30.0


def test_fund_performance_first_month_baseline_exclusion(perf_setup):
    db_client = perf_setup["db_client"]
    service = perf_setup["service"]

    with db_client.get_connection() as conn:
        conn.execute(
            text(
                "INSERT INTO fund_positions VALUES ('FundA', '2023-01-31', 0, 1000.0);"
            )
        )

    out_csv = perf_setup["output_dir"] / "perf.csv"

    # Assert custom exception raised when single-month baseline produces 0 performance rows
    with pytest.raises(EmptyPerformanceResultsError):
        service.run_performance_analysis(output_path=out_csv)