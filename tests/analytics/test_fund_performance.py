import sqlite3
from pathlib import Path
import pandas as pd
import pytest

from src.analytics.fund_performance import generate_best_performing_funds


@pytest.fixture
def test_environment(tmp_path: Path):
    """Sets up a temporary database and fund performance SQL query file."""
    db_path = tmp_path / "reference_data.db"
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)

    perf_sql_path = sql_dir / "monthly_fund_performance.sql"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE fund_positions (
            fund_name TEXT,
            report_date TEXT,
            financial_type TEXT,
            symbol TEXT,
            security_name TEXT,
            sedol TEXT,
            price REAL,
            quantity REAL,
            realised_pl REAL,
            market_value REAL
        );
    """
    )
    conn.commit()
    conn.close()

    perf_sql_path.write_text(
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

    return {
        "db_path": db_path,
        "perf_sql_path": perf_sql_path,
        "output_dir": tmp_path / "output",
    }


def test_fund_performance_ror_calculation_and_ranking(test_environment):
    """Validates RoR formula ((MV_end - MV_start + PL) / MV_start) and monthly ranking."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        -- Month 1 (Jan 2023): Baseline
        INSERT INTO fund_positions VALUES ('FundA', '2023-01-31', 'Equities', 'X', 'X', 'X', 10, 100, 0, 1000.0);
        INSERT INTO fund_positions VALUES ('FundB', '2023-01-31', 'Equities', 'Y', 'Y', 'Y', 20, 100, 0, 2000.0);

        -- Month 2 (Feb 2023): Performance Evaluation
        -- FundA: MV_start=1000, MV_end=1200, PL=100 -> RoR = (1200 - 1000 + 100) / 1000 = 30%
        INSERT INTO fund_positions VALUES ('FundA', '2023-02-28', 'Equities', 'X', 'X', 'X', 12, 100, 100, 1200.0);
        -- FundB: MV_start=2000, MV_end=2200, PL=0   -> RoR = (2200 - 2000 + 0)   / 2000 = 10%
        INSERT INTO fund_positions VALUES ('FundB', '2023-02-28', 'Equities', 'Y', 'Y', 'Y', 22, 100, 0, 2200.0);
    """
    )
    conn.commit()
    conn.close()

    out_csv = test_environment["output_dir"] / "perf.csv"
    df = generate_best_performing_funds(
        test_environment["db_path"], out_csv, test_environment["perf_sql_path"]
    )

    assert len(df) == 1  # Only Feb 2023 evaluated (Jan baseline excluded)
    feb = df.iloc[0]

    assert feb["report_date"] == "2023-02-28"
    assert feb["best_performing_fund"] == "FundA"
    assert feb["fund_mv_start"] == 1000.0
    assert feb["fund_mv_end"] == 1200.0
    assert feb["realized_pl"] == 100.0
    assert feb["ror_pct"] == 30.0


def test_fund_performance_first_month_baseline_exclusion(test_environment):
    """Ensures Month 1 is excluded from performance output since starting MV is unknown."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        INSERT INTO fund_positions VALUES ('FundA', '2023-01-31', 'Equities', 'X', 'X', 'X', 10, 100, 0, 1000.0);
    """
    )
    conn.commit()
    conn.close()

    out_csv = test_environment["output_dir"] / "perf.csv"
    df = generate_best_performing_funds(
        test_environment["db_path"], out_csv, test_environment["perf_sql_path"]
    )

    assert len(df) == 0


def test_fund_performance_file_not_found_errors(test_environment):
    """Verifies FileNotFoundError raised when database file is missing."""
    out_csv = test_environment["output_dir"] / "out.csv"
    bad_db = test_environment["output_dir"] / "missing.db"

    with pytest.raises(FileNotFoundError):
        generate_best_performing_funds(
            bad_db, out_csv, test_environment["perf_sql_path"]
        )