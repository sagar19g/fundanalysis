import sqlite3
from pathlib import Path
import pandas as pd
import pytest

from src.analytics.price_reconciliation import (
    prepare_indexed_database,
    run_price_reconciliation,
)


@pytest.fixture
def test_environment(tmp_path: Path):
    """Sets up a temporary database and price reconciliation SQL query file."""
    db_path = tmp_path / "reference_data.db"
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)

    recon_sql_path = sql_dir / "price_reconciliation.sql"

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

        CREATE TABLE equity_prices (
            SYMBOL TEXT,
            PRICE REAL,
            DATETIME TEXT
        );

        CREATE TABLE bond_prices (
            ISIN TEXT,
            PRICE REAL,
            DATETIME TEXT
        );

        CREATE TABLE bond_reference (
            SEDOL TEXT,
            "SECURITY NAME" TEXT,
            ISIN TEXT
        );
    """
    )
    conn.commit()
    conn.close()

    recon_sql_path.write_text(
        """
        WITH raw_positions AS (
            SELECT DISTINCT fund_name, report_date, financial_type, symbol, security_name, sedol, price AS fund_price,
            CASE WHEN LOWER(financial_type) LIKE '%equit%' THEN 'EQUITY' WHEN LOWER(financial_type) LIKE '%bond%' OR LOWER(financial_type) LIKE '%debt%' THEN 'BOND' ELSE 'OTHER' END AS asset_class
            FROM fund_positions WHERE LOWER(financial_type) NOT LIKE '%cash%'
        ),
        bond_isin_mappings AS (
            SELECT DISTINCT p.sedol, p.security_name, br.ISIN FROM raw_positions p
            LEFT JOIN bond_reference br ON (br.SEDOL = p.sedol AND p.sedol IS NOT NULL AND p.sedol <> '') OR (br."SECURITY NAME" = p.security_name AND p.security_name IS NOT NULL)
            WHERE p.asset_class = 'BOND'
        ),
        equity_prices_asof AS (
            SELECT p.fund_name, p.report_date, p.symbol, ep.PRICE AS ref_price, ep.iso_ref_date AS ref_price_date
            FROM raw_positions p LEFT JOIN norm_eq_prices ep ON ep.SYMBOL = p.symbol
            AND ep.iso_ref_date = (SELECT MAX(ep_sub.iso_ref_date) FROM norm_eq_prices ep_sub WHERE ep_sub.SYMBOL = p.symbol AND ep_sub.iso_ref_date <= p.report_date)
            WHERE p.asset_class = 'EQUITY'
        ),
        bond_prices_asof AS (
            SELECT p.fund_name, p.report_date, p.security_name, p.sedol, bp.PRICE AS ref_price, bp.iso_ref_date AS ref_price_date
            FROM raw_positions p LEFT JOIN bond_isin_mappings bm ON (bm.sedol = p.sedol AND p.sedol IS NOT NULL AND p.sedol <> '') OR (bm.security_name = p.security_name AND p.security_name IS NOT NULL)
            LEFT JOIN norm_bd_prices bp ON bp.ISIN = bm.ISIN AND bp.iso_ref_date = (SELECT MAX(bp_sub.iso_ref_date) FROM norm_bd_prices bp_sub WHERE bp_sub.ISIN = bm.ISIN AND bp_sub.iso_ref_date <= p.report_date)
            WHERE p.asset_class = 'BOND'
        ),
        reconciled_positions AS (
            SELECT rp.fund_name, rp.report_date, rp.financial_type, rp.symbol, rp.security_name, rp.sedol, rp.fund_price,
            COALESCE(eq.ref_price, bd.ref_price) AS ref_price, COALESCE(eq.ref_price_date, bd.ref_price_date) AS ref_price_date
            FROM raw_positions rp LEFT JOIN equity_prices_asof eq ON rp.asset_class = 'EQUITY' AND rp.fund_name = eq.fund_name AND rp.report_date = eq.report_date AND rp.symbol = eq.symbol
            LEFT JOIN bond_prices_asof bd ON rp.asset_class = 'BOND' AND rp.fund_name = bd.fund_name AND rp.report_date = bd.report_date AND ((rp.sedol = bd.sedol AND rp.sedol IS NOT NULL) OR (rp.security_name = bd.security_name AND rp.security_name IS NOT NULL))
        )
        SELECT DISTINCT fund_name, report_date, financial_type, symbol, security_name, sedol, fund_price, ref_price, ref_price_date,
        ROUND(fund_price - ref_price, 4) AS price_break, ROUND(ABS(fund_price - ref_price) / NULLIF(ref_price, 0) * 100, 2) AS price_break_pct,
        CASE WHEN ref_price IS NULL THEN 'MISSING_REF_PRICE' WHEN ABS(fund_price - ref_price) > 0.01 THEN 'PRICE_BREAK' ELSE 'MATCH' END AS status
        FROM reconciled_positions;
    """,
        encoding="utf-8",
    )

    return {
        "db_path": db_path,
        "recon_sql_path": recon_sql_path,
        "output_dir": tmp_path / "output",
    }


def test_prepare_indexed_database_date_parsing(test_environment):
    """Tests slash date normalization (US & EU formats) into temp tables."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        INSERT INTO equity_prices VALUES ('AAPL', 150.0, '8/31/2023');   -- US M/D/YYYY -> 2023-08-31
        INSERT INTO bond_prices VALUES ('US12345', 99.5, '2023-08-30');   -- ISO YYYY-MM-DD -> 2023-08-30
    """
    )
    conn.commit()

    prepare_indexed_database(conn)

    eq_df = pd.read_sql_query("SELECT * FROM norm_eq_prices", conn)
    bd_df = pd.read_sql_query("SELECT * FROM norm_bd_prices", conn)
    conn.close()

    assert eq_df.iloc[0]["iso_ref_date"] == "2023-08-31"
    assert bd_df.iloc[0]["iso_ref_date"] == "2023-08-30"


def test_reconciliation_exact_and_fallback_price_matching(test_environment):
    """Tests matching exact EOM reference price and falling back to latest price <= report_date."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price)
        VALUES ('Whitestone', '2023-08-31', 'Equities', 'AAPL', 150.0);
        INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price)
        VALUES ('Whitestone', '2023-08-31', 'Equities', 'MSFT', 300.0);

        -- AAPL has exact date match
        INSERT INTO equity_prices VALUES ('AAPL', 150.0, '8/31/2023');
        -- MSFT only has historical fallback match (8/25/2023 < 8/31/2023)
        INSERT INTO equity_prices VALUES ('MSFT', 295.0, '8/25/2023');
        -- MSFT future price should be IGNORED (9/5/2023 > 8/31/2023)
        INSERT INTO equity_prices VALUES ('MSFT', 310.0, '9/5/2023');
    """
    )
    conn.commit()
    conn.close()

    out_csv = test_environment["output_dir"] / "recon.csv"
    df = run_price_reconciliation(
        test_environment["db_path"], out_csv, test_environment["recon_sql_path"]
    )

    aapl = df[df["symbol"] == "AAPL"].iloc[0]
    msft = df[df["symbol"] == "MSFT"].iloc[0]

    assert aapl["ref_price"] == 150.0
    assert aapl["ref_price_date"] == "2023-08-31"
    assert aapl["status"] == "MATCH"

    assert msft["ref_price"] == 295.0
    assert msft["ref_price_date"] == "2023-08-25"
    assert msft["status"] == "PRICE_BREAK"


def test_reconciliation_missing_price_and_cash_exclusion(test_environment):
    """Tests missing reference price assignment and verifies CASH asset exclusion."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price)
        VALUES ('Whitestone', '2023-08-31', 'Equities', 'UNKNOWN_SYM', 50.0);
        INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price)
        VALUES ('Whitestone', '2023-08-31', 'Cash Equivalent', 'USD_CASH', 1.0);
    """
    )
    conn.commit()
    conn.close()

    out_csv = test_environment["output_dir"] / "recon.csv"
    df = run_price_reconciliation(
        test_environment["db_path"], out_csv, test_environment["recon_sql_path"]
    )

    assert len(df) == 1  # USD_CASH excluded
    unknown = df.iloc[0]
    assert unknown["symbol"] == "UNKNOWN_SYM"
    assert pd.isna(unknown["ref_price"])
    assert unknown["status"] == "MISSING_REF_PRICE"


def test_reconciliation_price_break_variance_math(test_environment):
    """Verifies math for price break absolute variance and percentage calculations."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price)
        VALUES ('Whitestone', '2023-08-31', 'Equities', 'TSLA', 200.0);
        INSERT INTO equity_prices VALUES ('TSLA', 250.0, '2023-08-31');
    """
    )
    conn.commit()
    conn.close()

    out_csv = test_environment["output_dir"] / "recon.csv"
    df = run_price_reconciliation(
        test_environment["db_path"], out_csv, test_environment["recon_sql_path"]
    )

    row = df.iloc[0]
    assert row["price_break"] == -50.0
    assert row["price_break_pct"] == 20.0
    assert row["status"] == "PRICE_BREAK"


def test_reconciliation_bond_isin_resolution(test_environment):
    """Verifies bond mapping from SEDOL / Security Name to ISIN prior to price lookup."""
    conn = sqlite3.connect(test_environment["db_path"])
    cursor = conn.cursor()

    cursor.executescript(
        """
        INSERT INTO fund_positions (fund_name, report_date, financial_type, security_name, sedol, price)
        VALUES ('Whitestone', '2023-08-31', 'Government Bond', 'US TREASURY', 'B123456', 98.0);

        INSERT INTO bond_reference VALUES ('B123456', 'US TREASURY', 'US999999999');
        INSERT INTO bond_prices VALUES ('US999999999', 98.0, '2023-08-31');
    """
    )
    conn.commit()
    conn.close()

    out_csv = test_environment["output_dir"] / "recon.csv"
    df = run_price_reconciliation(
        test_environment["db_path"], out_csv, test_environment["recon_sql_path"]
    )

    assert len(df) == 1
    assert df.iloc[0]["ref_price"] == 98.0
    assert df.iloc[0]["status"] == "MATCH"


def test_reconciliation_file_not_found_errors(test_environment):
    """Verifies FileNotFoundError raised when database file is missing."""
    out_csv = test_environment["output_dir"] / "out.csv"
    bad_db = test_environment["output_dir"] / "missing.db"

    with pytest.raises(FileNotFoundError):
        run_price_reconciliation(
            bad_db, out_csv, test_environment["recon_sql_path"]
        )