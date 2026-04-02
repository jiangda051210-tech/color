"""
Database backup & recovery for SENIA Elite.

Provides automated backup of SQLite databases and critical config files
with rotation, integrity verification, and optional compression.

Usage:
    mgr = BackupManager(
        backup_dir=Path("./backups"),
        sources=[
            Path("quality_history.sqlite"),
            Path("innovation_state.sqlite"),
        ],
    )
    result = mgr.backup()          # Create a backup
    mgr.rotate(keep=7)             # Keep only 7 most recent
    mgr.verify(result.backup_path) # Verify integrity
    mgr.list_backups()             # List all backups
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackupResult:
    backup_path: Path
    sources: list[str]
    size_bytes: int
    sha256: str
    created_at: str
    compressed: bool
    duration_sec: float


class BackupManager:
    """Automated backup manager for SQLite databases and config files."""

    def __init__(
        self,
        backup_dir: Path,
        sources: list[Path] | None = None,
        config_files: list[Path] | None = None,
        compress: bool = True,
    ) -> None:
        self._backup_dir = backup_dir
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._sources = sources or []
        self._config_files = config_files or []
        self._compress = compress
        self._manifest_path = backup_dir / "_backup_manifest.jsonl"

    def backup(self) -> BackupResult:
        """Create a backup of all registered sources."""
        start = time.perf_counter()
        ts = time.strftime("%Y%m%d_%H%M%S")
        snapshot_dir = self._backup_dir / f"snapshot_{ts}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        backed_up: list[str] = []

        # Backup SQLite databases using online backup API
        for db_path in self._sources:
            if not db_path.exists():
                continue
            dst = snapshot_dir / db_path.name
            self._backup_sqlite(db_path, dst)
            backed_up.append(str(db_path))

        # Copy config files
        for cfg in self._config_files:
            if not cfg.exists():
                continue
            dst = snapshot_dir / cfg.name
            shutil.copy2(str(cfg), str(dst))
            backed_up.append(str(cfg))

        # Optionally compress the snapshot
        final_path: Path
        if self._compress:
            archive = shutil.make_archive(
                str(snapshot_dir), "gztar", str(snapshot_dir.parent), snapshot_dir.name
            )
            final_path = Path(archive)
            shutil.rmtree(snapshot_dir)
        else:
            final_path = snapshot_dir

        # Compute checksum
        sha = self._file_sha256(final_path) if final_path.is_file() else ""
        size = final_path.stat().st_size if final_path.is_file() else self._dir_size(final_path)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        elapsed = time.perf_counter() - start

        result = BackupResult(
            backup_path=final_path,
            sources=backed_up,
            size_bytes=size,
            sha256=sha,
            created_at=created_at,
            compressed=self._compress,
            duration_sec=round(elapsed, 2),
        )

        # Append to manifest
        self._write_manifest(result)
        return result

    def rotate(self, keep: int = 7) -> int:
        """Delete old backups, keeping only the most recent `keep` backups. Returns deleted count."""
        backups = sorted(self._list_backup_files(), key=lambda p: p.stat().st_mtime, reverse=True)
        deleted = 0
        for old in backups[keep:]:
            if old.is_dir():
                shutil.rmtree(old)
            else:
                old.unlink()
            deleted += 1
        return deleted

    def verify(self, backup_path: Path) -> dict[str, Any]:
        """Verify a backup's integrity."""
        if not backup_path.exists():
            return {"ok": False, "error": "backup not found"}

        result: dict[str, Any] = {"path": str(backup_path), "ok": True}

        if backup_path.is_file() and backup_path.suffix in (".gz", ".tar"):
            result["sha256"] = self._file_sha256(backup_path)
            result["size_bytes"] = backup_path.stat().st_size
        elif backup_path.is_dir():
            # Verify each SQLite database
            for db_file in backup_path.glob("*.sqlite"):
                try:
                    conn = sqlite3.connect(str(db_file))
                    conn.execute("PRAGMA integrity_check")
                    conn.close()
                    result[db_file.name] = "integrity_ok"
                except sqlite3.Error as exc:
                    result[db_file.name] = f"integrity_failed: {exc}"
                    result["ok"] = False

        return result

    def list_backups(self) -> list[dict[str, Any]]:
        """List all backups with metadata."""
        backups: list[dict[str, Any]] = []
        for path in sorted(self._list_backup_files(), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = path.stat()
            backups.append({
                "path": str(path),
                "name": path.name,
                "size_bytes": stat.st_size if path.is_file() else self._dir_size(path),
                "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
            })
        return backups

    def status(self) -> dict[str, Any]:
        """Return backup status summary."""
        backups = self.list_backups()
        return {
            "backup_dir": str(self._backup_dir),
            "total_backups": len(backups),
            "latest": backups[0] if backups else None,
            "sources": [str(s) for s in self._sources],
            "config_files": [str(c) for c in self._config_files],
            "compress": self._compress,
        }

    # ─── Internal ──────────────────────────────────

    @staticmethod
    def _backup_sqlite(src: Path, dst: Path) -> None:
        """Use SQLite online backup API for safe hot backup."""
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _dir_size(path: Path) -> int:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    def _list_backup_files(self) -> list[Path]:
        results: list[Path] = []
        for item in self._backup_dir.iterdir():
            if item.name.startswith("snapshot_"):
                results.append(item)
            elif item.name.startswith("snapshot_") and item.suffix == ".gz":
                results.append(item)
        return results

    def _write_manifest(self, result: BackupResult) -> None:
        entry = {
            "path": str(result.backup_path),
            "sources": result.sources,
            "size_bytes": result.size_bytes,
            "sha256": result.sha256,
            "created_at": result.created_at,
            "compressed": result.compressed,
        }
        try:
            with self._manifest_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
