import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, Engine, Connection

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Abstracts connection pooling and transactions across SQLite, Postgres, etc."""

    def __init__(self, database_url: str):
        self.engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            echo=False
        )

    @contextmanager
    def get_connection(self) -> Generator[Connection, None, None]:
        """Provides a transaction-managed SQLAlchemy Connection."""
        connection = self.engine.connect()
        transaction = connection.begin()
        try:
            yield connection
            transaction.commit()
        except Exception as e:
            transaction.rollback()
            logger.error(f"Database transaction error: {e}")
            raise
        finally:
            connection.close()