from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AppConfig(BaseSettings):
    app_env: str = "dev"
    log_level: str = "INFO"

    # Default URI points to SQLite; overridden in Prod by DATABASE_URL env var
    database_url: str = f"sqlite:///{PROJECT_ROOT}/data/reference_data.db"

    raw_data_dir: Path = PROJECT_ROOT / "data" / "external-funds"
    output_dir: Path = PROJECT_ROOT / "data" / "output"
    sql_dir: Path = PROJECT_ROOT / "database" / "sql"

    known_funds: tuple[str, ...] = (
        "Whitestone", "Wallington", "Catalysm", "Belaware", "Gohen",
        "Applebead", "Magnum", "Trustmind", "Leeder", "Virtous"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


config = AppConfig()