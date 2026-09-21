"""SQLAlchemy database engine and session lifecycle helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Base class shared by every database model."""


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield one request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_database_tables() -> None:
    """Create the v0.1 schema when it does not exist yet."""
    # Import registers all model classes on Base.metadata before create_all runs.
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def database_is_available() -> bool:
    """Return whether a lightweight PostgreSQL query succeeds."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

