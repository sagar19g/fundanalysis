import logging
import sqlite3
from pathlib import Path
import pandas as pd

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
SCRIPT_DIR = Path(__file__).resolve().parent

def generate_best_performing_funds(
    db_path: str | Path,
    output_csv_path: str | Path,
    sql_file_path: str | Path = None,
) -> pd.DataFrame:
    """Computes monthly Rate of Return across funds, identifies top performers,

    and exports analysis to CSV.
    """
    db_path = Path(db_path)
    output_csv_path = Path(output_csv_path)

    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found at: {db_path.resolve()}")

    if sql_file_path is None:
        sql_file_path = SCRIPT_DIR / "sql" / "monthly_fund_performance.sql"
    else:
        sql_file_path = Path(sql_file_path)

    if not sql_file_path.exists():
        raise FileNotFoundError(
            f"Could not find SQL file at resolved path: {sql_file_path.resolve()}"
        )

    query = sql_file_path.read_text(encoding="utf-8")

    logging.info("Executing top fund performance analysis query...")
    conn = sqlite3.connect(db_path)
    df_top_funds = pd.read_sql_query(query, conn)
    conn.close()

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df_top_funds.to_csv(output_csv_path, index=False)
    logging.info(f"Performance analysis complete! Saved to {output_csv_path}")

    return df_top_funds


if __name__ == "__main__":
    DB_FILE = "data/reference_data.db"
    OUTPUT_FILE = "data/output/best_performing_funds.csv"

    df_results = generate_best_performing_funds(DB_FILE, OUTPUT_FILE)
    print(df_results)