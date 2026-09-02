from pathlib import Path
import pytest
from sqlalchemy import text

from src.core.db_client import DatabaseClient
from src.repositories.reconciliation_repo import SQLiteReconciliationRepository
from src.services.reconciliation import PriceReconciliationService


@pytest.fixture
def recon_setup(tmp_path: Path):
    db_path = tmp_path / "test_recon.db"
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)

    db_client = DatabaseClient(database_url=f"sqlite:///{db_path}")

    with db_client.get_connection() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE fund_positions (
                fund_name TEXT, report_date TEXT, financial_type TEXT,
                symbol TEXT, security_name TEXT, sedol TEXT, price REAL
            );
        """
            )
        )
        conn.execute(
            text("CREATE TABLE equity_prices (SYMBOL TEXT, PRICE REAL, DATETIME TEXT);")
        )
        conn.execute(
            text("CREATE TABLE bond_prices (ISIN TEXT, PRICE REAL, DATETIME TEXT);")
        )
        conn.execute(
            text("CREATE TABLE bond_reference (SEDOL TEXT, \"SECURITY NAME\" TEXT, ISIN TEXT);")
        )

    sql_file = sql_dir / "price_reconciliation.sql"
    sql_file.write_text(
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

    repo = SQLiteReconciliationRepository(db_client=db_client, sql_dir=sql_dir)
    service = PriceReconciliationService(repository=repo)

    return {
        "db_client": db_client,
        "service": service,
        "output_dir": tmp_path / "output",
    }


def test_reconciliation_exact_and_historical_fallback(recon_setup):
    db_client = recon_setup["db_client"]
    service = recon_setup["service"]

    with db_client.get_connection() as conn:
        conn.execute(
            text(
                """
            INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price) VALUES 
                ('Whitestone', '2023-08-31', 'Equities', 'AAPL', 150.0),
                ('Whitestone', '2023-08-31', 'Equities', 'MSFT', 300.0);
        """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO equity_prices VALUES 
                ('AAPL', 150.0, '8/31/2023'),
                ('MSFT', 295.0, '8/25/2023'),
                ('MSFT', 310.0, '9/5/2023');
        """
            )
        )

    out_csv = recon_setup["output_dir"] / "recon.csv"
    df = service.run_reconciliation(output_path=out_csv)

    aapl = df[df["symbol"] == "AAPL"].iloc[0]
    msft = df[df["symbol"] == "MSFT"].iloc[0]

    assert aapl["status"] == "MATCH"
    assert aapl["ref_price"] == 150.0

    assert msft["status"] == "PRICE_BREAK"
    assert msft["ref_price"] == 295.0
    assert msft["ref_price_date"] == "2023-08-25"


def test_reconciliation_cash_exclusion(recon_setup):
    db_client = recon_setup["db_client"]
    service = recon_setup["service"]

    with db_client.get_connection() as conn:
        conn.execute(
            text(
                """
            INSERT INTO fund_positions (fund_name, report_date, financial_type, symbol, price)
            VALUES ('Whitestone', '2023-08-31', 'Cash Equivalent', 'USD_CASH', 1.0);
        """
            )
        )

    out_csv = recon_setup["output_dir"] / "recon.csv"
    df = service.run_reconciliation(output_path=out_csv)

    assert len(df) == 0  # CASH asset class excluded