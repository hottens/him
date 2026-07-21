"""Add Open Food Facts product fields on barcodes (all nullable)."""

from sqlalchemy.engine import Connection

from app.migrations.helpers import add_column_if_missing

VERSION = "003_barcode_product_fields"

_COLUMNS = [
    ("product_name", "VARCHAR"),
    ("brands", "VARCHAR"),
    ("keywords", "TEXT"),
    ("ingredients_en", "TEXT"),
    ("ingredients_hierarchy_en", "TEXT"),
    ("ingredients_nl", "TEXT"),
    ("ingredients_hierarchy_nl", "TEXT"),
    ("allergens", "TEXT"),
    ("nutriments", "TEXT"),
    ("energy_kcal_100g", "FLOAT"),
    ("energy_kcal_serving", "FLOAT"),
    ("last_scanned_at", "DATETIME"),
    ("product_fetched_at", "DATETIME"),
]


def upgrade(conn: Connection) -> None:
    for column, col_type in _COLUMNS:
        add_column_if_missing(conn, "barcodes", column, col_type)
