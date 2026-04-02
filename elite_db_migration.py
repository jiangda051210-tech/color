"""
Lightweight database schema migration for SENIA Elite SQLite databases.

Tracks applied migrations in a `_schema_migrations` table.
Each migration is a named SQL script executed exactly once.

Usage:
    from elite_db_migration import MigrationRunner

    runner = MigrationRunner(db_path)
    runner.add("001_initial", '''
        CREATE TABLE IF NOT EXISTS quality_runs (...);
    ''')
    runner.add("002_add_lot_index", '''
        CREATE INDEX IF NOT EXISTS idx_lot ON quality_runs(lot_id);
    ''')
    runner.run()  # Only executes unapplied migrations
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _Migration:
    name: str
    sql: str
    description: str = ""


class MigrationRunner:
    """Forward-only schema migration manager for SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._migrations: list[_Migration] = []

    def add(self, name: str, sql: str, description: str = "") -> None:
        """Register a migration. Migrations run in the order added."""
        if any(m.name == name for m in self._migrations):
            raise ValueError(f"Duplicate migration name: {name}")
        self._migrations.append(_Migration(name=name, sql=sql, description=description))

    def run(self) -> list[str]:
        """
        Execute all pending migrations inside a transaction.
        Returns list of migration names that were applied.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT DEFAULT ''
                )
            """)
            applied = {
                row[0]
                for row in conn.execute("SELECT name FROM _schema_migrations").fetchall()
            }

            newly_applied: list[str] = []
            for migration in self._migrations:
                if migration.name in applied:
                    continue
                conn.executescript(migration.sql)
                conn.execute(
                    "INSERT INTO _schema_migrations (name, applied_at, description) VALUES (?, ?, ?)",
                    (
                        migration.name,
                        time.strftime("%Y-%m-%dT%H:%M:%S"),
                        migration.description,
                    ),
                )
                conn.commit()
                newly_applied.append(migration.name)

            return newly_applied
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        """Return migration status."""
        if not self._db_path.exists():
            return {
                "db_path": str(self._db_path),
                "total_migrations": len(self._migrations),
                "applied": 0,
                "pending": len(self._migrations),
                "pending_names": [m.name for m in self._migrations],
            }

        conn = sqlite3.connect(str(self._db_path))
        try:
            try:
                rows = conn.execute("SELECT name, applied_at FROM _schema_migrations ORDER BY applied_at").fetchall()
            except sqlite3.OperationalError:
                rows = []

            applied_names = {r[0] for r in rows}
            pending = [m.name for m in self._migrations if m.name not in applied_names]

            return {
                "db_path": str(self._db_path),
                "total_migrations": len(self._migrations),
                "applied": len(applied_names),
                "pending": len(pending),
                "applied_list": [{"name": r[0], "applied_at": r[1]} for r in rows],
                "pending_names": pending,
            }
        finally:
            conn.close()


def build_quality_history_migrations() -> MigrationRunner:
    """Pre-built migrations for the quality_history database."""
    runner = MigrationRunner(Path("quality_history.sqlite"))

    runner.add(
        "001_initial_schema",
        """
        CREATE TABLE IF NOT EXISTS quality_runs (
            run_id TEXT PRIMARY KEY,
            lot_id TEXT,
            line_id TEXT,
            product_code TEXT,
            profile TEXT,
            avg_de REAL,
            p95_de REAL,
            max_de REAL,
            decision TEXT,
            confidence REAL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_qr_lot ON quality_runs(lot_id);
        CREATE INDEX IF NOT EXISTS idx_qr_created ON quality_runs(created_at);
        """,
        description="Initial quality_runs table with lot and timestamp indexes",
    )

    runner.add(
        "002_add_customer_fields",
        """
        ALTER TABLE quality_runs ADD COLUMN customer_id TEXT DEFAULT '';
        ALTER TABLE quality_runs ADD COLUMN customer_tier TEXT DEFAULT 'standard';
        """,
        description="Add customer tracking fields",
    )

    runner.add(
        "003_add_operator_field",
        """
        ALTER TABLE quality_runs ADD COLUMN operator_id TEXT DEFAULT '';
        """,
        description="Add operator tracking for skill analysis",
    )

    runner.add(
        "004_add_batch_blend_fields",
        """
        ALTER TABLE quality_runs ADD COLUMN batch_group TEXT DEFAULT '';
        ALTER TABLE quality_runs ADD COLUMN ink_lot_id TEXT DEFAULT '';
        """,
        description="Add batch blending and ink lot tracking",
    )

    return runner
