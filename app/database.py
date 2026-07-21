"""Database configuration, session management, and schema initialization."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

from .migrations import run_migrations

# Database file location - use /data for Docker volume persistence
DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/inventory.db")

# Ensure directory exists
_db_dir = os.path.dirname(DATABASE_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # Needed for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind=None) -> list[str]:
    """
    Create missing tables from ORM models, then apply versioned migrations.

    ``create_all`` only creates *new* tables — it never alters existing ones.
    Migrations are additive (nullable columns / new tables) and idempotent.
    """
    target = bind or engine
    Base.metadata.create_all(bind=target)
    return run_migrations(target)
