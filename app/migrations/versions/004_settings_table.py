"""Ensure settings key/value table exists."""

from sqlalchemy.engine import Connection

from app.migrations.helpers import create_table_if_missing

VERSION = "004_settings_table"


def upgrade(conn: Connection) -> None:
    create_table_if_missing(
        conn,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        )
        """,
    )
