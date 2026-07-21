"""Add items.active_barcode_id (nullable, no FK to avoid circular dependency)."""

from sqlalchemy.engine import Connection

from app.migrations.helpers import add_column_if_missing

VERSION = "002_items_active_barcode"


def upgrade(conn: Connection) -> None:
    add_column_if_missing(conn, "items", "active_barcode_id", "INTEGER")
