"""
Versioned database migrations.

Each module in ``versions/`` exposes:
  - VERSION: str   (sortable, e.g. \"001_recipes_source_url\")
  - upgrade(conn): apply additive schema changes

Applied versions are recorded in ``schema_migrations`` so they run once.
All migrations must be additive (ADD COLUMN / CREATE TABLE) and preserve rows.
"""

from __future__ import annotations

import importlib
import pkgutil
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from . import versions as versions_pkg
from .helpers import create_table_if_missing


def _ensure_migrations_table(conn: Connection) -> None:
    create_table_if_missing(
        conn,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR PRIMARY KEY,
            applied_at VARCHAR NOT NULL
        )
        """,
    )


def _applied_versions(conn: Connection) -> set[str]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def _load_migrations() -> list[tuple[str, Callable[[Connection], None]]]:
    migrations: list[tuple[str, Callable[[Connection], None]]] = []
    for module_info in pkgutil.iter_modules(versions_pkg.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{versions_pkg.__name__}.{module_info.name}")
        version = getattr(module, "VERSION", None)
        upgrade = getattr(module, "upgrade", None)
        if not version or not callable(upgrade):
            raise RuntimeError(
                f"Migration module {module_info.name} must define VERSION and upgrade()"
            )
        migrations.append((version, upgrade))
    migrations.sort(key=lambda item: item[0])
    return migrations


def run_migrations(engine: Engine) -> list[str]:
    """
    Apply all pending migrations in order.

    Returns the list of newly applied version ids.
    Safe to call on every startup; already-applied versions are skipped.
    """
    applied_now: list[str] = []
    with engine.begin() as conn:
        _ensure_migrations_table(conn)
        done = _applied_versions(conn)
        for version, upgrade in _load_migrations():
            if version in done:
                continue
            upgrade(conn)
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (:version, :applied_at)"
                ),
                {
                    "version": version,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            applied_now.append(version)
    return applied_now
