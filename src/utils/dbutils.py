from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]  # Points to project root (fundanalysis/)

def resolve_db_path() -> Path:
    """Locates reference_data.db whether it's in database/ or data/."""
    db_in_data = PROJECT_ROOT / "data" / "reference_data.db"
    return db_in_data