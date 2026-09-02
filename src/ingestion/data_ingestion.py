import sqlite3
import pandas as pd
from pathlib import Path
import re
from dateutil import parser

# Known master universe of 10 funds
KNOWN_FUNDS = [
    "Whitestone",
    "Wallington",
    "Catalysm",
    "Belaware",
    "Gohen",
    "Applebead",
    "Magnum",
    "Trustmind",
    "Leeder",
    "Virtous",
]


def normalize_fund_name(raw_name: str) -> str:
    """Matches raw extracted string against the known fund list."""
    for fund in KNOWN_FUNDS:
        if fund.lower() in raw_name.lower():
            return fund
    return raw_name.strip()  # Fallback to raw string if unmatched


def ingest_fund_csv(
    db_path: str, csv_path: str, fund_name: str, report_date: str
) -> int:
    column_mapping = {
        "FINANCIAL TYPE": "financial_type",
        "SYMBOL": "symbol",
        "SECURITY NAME": "security_name",
        "SEDOL": "sedol",
        "PRICE": "price",
        "QUANTITY": "quantity",
        "REALISED P/L": "realised_pl",
        "MARKET VALUE": "market_value",
    }

    df = pd.read_csv(csv_path)

    df.columns = df.columns.str.strip()
    df.rename(columns=column_mapping, inplace=True)

    df["fund_name"] = fund_name
    df["report_date"] = report_date

    required_cols = [
        "fund_name",
        "report_date",
        "financial_type",
        "symbol",
        "security_name",
        "price",
        "quantity",
        "realised_pl",
        "market_value",
    ]
    df = df[required_cols]

    conn = sqlite3.connect(db_path)
    df.to_sql("fund_positions", conn, if_exists="append", index=False)
    rows_inserted = len(df)
    conn.close()

    return rows_inserted


def extract_eom_date(datestring: str) -> str:
    date_match = re.search(
        r"\b(\d{4}[-/_.]\d{1,2}[-/_.]\d{1,2}|\d{1,2}[-/_.]\d{1,2}[-/_.]\d{4}|\d{8})\b",
        datestring,
    )

    date_str = date_match.group(1) if date_match else datestring
    parsed_dt = parser.parse(date_str, fuzzy=True, dayfirst=False)

    return parsed_dt.strftime("%Y-%m-%d")


def populate_fund_data(DB_FILE: str, FUND_EOM_DATA_DIR: str) -> None:
    fund_data_dir = Path(FUND_EOM_DATA_DIR)

    if not fund_data_dir.exists():
        print(f"Directory {FUND_EOM_DATA_DIR} does not exist.")
        return

    for csv_file in fund_data_dir.glob("*.csv"):
        parts = csv_file.stem.split(".")

        raw_fund_name = parts[0]
        fund_name = normalize_fund_name(raw_fund_name)
        report_date = extract_eom_date(csv_file.name)

        try:
            rows_inserted = ingest_fund_csv(DB_FILE, csv_file, fund_name, report_date)
            print(f"Inserted {rows_inserted} rows for '{fund_name}' (Raw: '{raw_fund_name}') on {report_date}.")
        except Exception as e:
            print(f"Error processing file {csv_file.name}: {e}")


if __name__ == "__main__":
    DB_FILE = "data/reference_data.db"
    FUND_EOM_DATA_DIR = "data/external-funds/"

    populate_fund_data(DB_FILE, FUND_EOM_DATA_DIR)