import logging
import sqlite3
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]


def init_database(db_path: Path, sql_file_path: Path) -> None:
    """Executes master reference SQL script and initializes SQLite database schema."""
    if not sql_file_path.exists():
        raise FileNotFoundError(
            f"SQL file not found at resolved path: {sql_file_path.resolve()}"
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)

    logging.info(f"Reading schema from {sql_file_path.name}...")
    sql_script = sql_file_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(sql_script)
    conn.commit()
    conn.close()

    logging.info(f"Database successfully initialized at {db_path.resolve()}")


if __name__ == "__main__":
    DB_FILE = PROJECT_ROOT / "data" / "reference_data.db"

    # Path updated to point inside database/sql/
    MASTER_SQL = PROJECT_ROOT / "database" / "sql" / "master-reference-sql.sql"

    init_database(DB_FILE, MASTER_SQL)