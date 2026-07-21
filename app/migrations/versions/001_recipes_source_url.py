"""Add recipes.source_url (nullable)."""

from sqlalchemy.engine import Connection

from app.migrations.helpers import add_column_if_missing

VERSION = "001_recipes_source_url"


def upgrade(conn: Connection) -> None:
    add_column_if_missing(conn, "recipes", "source_url", "VARCHAR")
