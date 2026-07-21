"""Safe SQLite migration helpers — additive only, never drop data."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def table_exists(conn: Connection, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table},
    ).fetchone()
    return row is not None


def table_columns(conn: Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in result.fetchall()}


def add_column_if_missing(
    conn: Connection,
    table: str,
    column: str,
    col_type: str,
) -> bool:
    """
    ADD COLUMN when missing. SQLite only allows nullable columns without DEFAULT
    (or with a constant default) on existing tables — keep new fields nullable.
    Returns True if the column was added.
    """
    if not table_exists(conn, table):
        return False
    if column in table_columns(conn, table):
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
    return True


def create_table_if_missing(conn: Connection, ddl: str) -> None:
    """Run a CREATE TABLE IF NOT EXISTS statement."""
    conn.execute(text(ddl))
