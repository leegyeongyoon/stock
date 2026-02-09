"""Database connection management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import settings
from src.database.models import Base


_engine = None
_SessionLocal = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory():
    """Get session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a database session with automatic cleanup."""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initialize database tables."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all database tables."""
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
