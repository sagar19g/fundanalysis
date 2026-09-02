import logging
import sqlite3
from pathlib import Path
import pandas as pd
from src.utils.dbutils import resolve_db_path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR  # Points to project root (fundanalysis/)


def prepare_indexed_database(conn: sqlite3.Connection) -> None:
    logging.info("Building temporary indexes and materialized price tables...")
    cursor = conn.cursor()

    cursor.executescript(
        """
        DROP TABLE IF EXISTS norm_eq_prices;
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

        CREATE INDEX idx_neq_sym_dt ON norm_eq_prices(SYMBOL, iso_ref_date DESC);

        DROP TABLE IF EXISTS norm_bd_prices;
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

        CREATE INDEX idx_nbd_isin_dt ON norm_bd_prices(ISIN, iso_ref_date DESC);
    """
    )
    conn.commit()


def run_price_reconciliation(
    db_path: str | Path,
    output_csv_path: str | Path,
    sql_file_path: str | Path = None,
) -> pd.DataFrame:
    """Reads SQL, executes indexed reconciliation query, and writes CSV output."""
    db_path = Path(db_path)
    output_csv_path = Path(output_csv_path)

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database file not found at: {db_path.resolve()}"
        )

    if sql_file_path is None:
        sql_file_path = SCRIPT_DIR / "sql" / "price_reconciliation.sql"
    else:
        sql_file_path = Path(sql_file_path)

    if not sql_file_path.exists():
        raise FileNotFoundError(
            f"Could not find SQL file at resolved path: {sql_file_path.resolve()}"
        )

    query = sql_file_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)

    # Execute indexing optimization step
    prepare_indexed_database(conn)

    logging.info("Executing price reconciliation query...")
    df_recon = pd.read_sql_query(query, conn)
    conn.close()

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df_recon.to_csv(output_csv_path, index=False)
    logging.info(
        f"Reconciliation complete! Exported {len(df_recon)} rows to {output_csv_path}"
    )

    return df_recon



if __name__ == "__main__":
    DB_FILE = resolve_db_path()
    print(DB_FILE)
    OUTPUT_FILE = "data/output/price_reconciliation.csv"

    run_price_reconciliation(DB_FILE, OUTPUT_FILE)