"""Tests for the versioned SQLite migration runner."""

from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.migrations import run_migrations
from app.migrations.helpers import table_columns


def _memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_legacy_schema(conn) -> None:
    """Schema as it existed before Open Food Facts / active barcode work."""
    conn.execute(text("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            location VARCHAR NOT NULL
        )
    """))
    conn.execute(text("""
        CREATE TABLE barcodes (
            id INTEGER PRIMARY KEY,
            code VARCHAR NOT NULL UNIQUE,
            item_id INTEGER NOT NULL,
            FOREIGN KEY(item_id) REFERENCES items(id)
        )
    """))
    conn.execute(text("""
        CREATE TABLE recipes (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            description TEXT,
            servings INTEGER,
            prep_time_minutes INTEGER,
            cook_time_minutes INTEGER,
            is_favorite BOOLEAN,
            created_at DATETIME
        )
    """))
    conn.execute(
        text("INSERT INTO items (id, name, location) VALUES (1, 'Milk', 'inventory')")
    )
    conn.execute(
        text("INSERT INTO barcodes (id, code, item_id) VALUES (1, '123', 1)")
    )
    conn.execute(
        text(
            "INSERT INTO recipes (id, name, servings, is_favorite, created_at) "
            "VALUES (1, 'Pasta', 4, 0, :ts)"
        ),
        {"ts": datetime.utcnow().isoformat()},
    )
    conn.commit()


class TestMigrations:
    def test_upgrade_preserves_existing_rows(self):
        engine = _memory_engine()
        with engine.connect() as conn:
            _create_legacy_schema(conn)

        applied = run_migrations(engine)
        assert applied  # at least one migration ran

        with engine.connect() as conn:
            item = conn.execute(text("SELECT id, name, location FROM items")).fetchone()
            assert item == (1, "Milk", "inventory")

            barcode = conn.execute(
                text("SELECT id, code, item_id FROM barcodes")
            ).fetchone()
            assert barcode == (1, "123", 1)

            recipe = conn.execute(text("SELECT id, name FROM recipes")).fetchone()
            assert recipe == (1, "Pasta")

            assert "active_barcode_id" in table_columns(conn, "items")
            assert "source_url" in table_columns(conn, "recipes")
            assert "product_name" in table_columns(conn, "barcodes")
            assert "energy_kcal_100g" in table_columns(conn, "barcodes")
            assert "settings" in {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }

    def test_migrations_are_idempotent(self):
        engine = _memory_engine()
        with engine.connect() as conn:
            _create_legacy_schema(conn)

        first = run_migrations(engine)
        second = run_migrations(engine)

        assert first
        assert second == []

        with engine.connect() as conn:
            versions = [
                row[0]
                for row in conn.execute(
                    text("SELECT version FROM schema_migrations ORDER BY version")
                )
            ]
            assert versions == first

    def test_new_nullable_columns_default_to_null(self):
        engine = _memory_engine()
        with engine.connect() as conn:
            _create_legacy_schema(conn)

        run_migrations(engine)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT product_name, energy_kcal_100g FROM barcodes WHERE code = '123'"
                )
            ).fetchone()
            assert row == (None, None)

            active = conn.execute(
                text("SELECT active_barcode_id FROM items WHERE id = 1")
            ).scalar()
            assert active is None
