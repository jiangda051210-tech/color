"""
Image lifecycle management for SENIA Elite.

Provides a storage abstraction layer with:
  - Local filesystem storage (default)
  - Pluggable cloud backends (S3/OSS/GCS via simple interface)
  - Automatic archival of old images to cold storage
  - Retention policies (auto-delete after N days)
  - Image compression for long-term storage
  - Metadata tracking in SQLite

Usage:
    store = ImageStore(root=Path("./image_archive"))
    ref = store.save(image_bytes, lot_id="L001", category="analysis")
    data = store.load(ref)
    store.cleanup(max_age_days=90)
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Protocol


class CloudBackend(Protocol):
    """Interface for pluggable cloud storage backends."""

    def upload(self, local_path: Path, remote_key: str) -> str: ...
    def download(self, remote_key: str, local_path: Path) -> None: ...
    def delete(self, remote_key: str) -> None: ...
    def exists(self, remote_key: str) -> bool: ...


@dataclass(frozen=True)
class ImageRef:
    """Reference to a stored image."""
    ref_id: str
    path: str
    sha256: str
    size_bytes: int
    category: str
    lot_id: str
    created_at: str


class ImageStore:
    """Local image storage with optional cloud archival."""

    def __init__(
        self,
        root: Path,
        db_path: Path | None = None,
        cloud: CloudBackend | None = None,
        compress_quality: int = 85,
    ) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path or (root / "_image_meta.sqlite")
        self._cloud = cloud
        self._compress_quality = compress_quality
        self._lock = RLock()
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    ref_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    category TEXT DEFAULT '',
                    lot_id TEXT DEFAULT '',
                    product_code TEXT DEFAULT '',
                    line_id TEXT DEFAULT '',
                    cloud_key TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_img_lot ON images(lot_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_img_created ON images(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_img_archived ON images(archived)")
            conn.commit()
        finally:
            conn.close()

    def save(
        self,
        data: bytes,
        lot_id: str = "",
        category: str = "analysis",
        product_code: str = "",
        line_id: str = "",
        filename: str | None = None,
    ) -> ImageRef:
        """Save image bytes and return a reference."""
        sha = hashlib.sha256(data).hexdigest()
        ts = time.strftime("%Y%m%d_%H%M%S")
        ref_id = f"{ts}_{sha[:12]}"

        # Organize by date/category
        date_dir = time.strftime("%Y/%m/%d")
        rel_dir = Path(category) / date_dir
        abs_dir = self._root / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix if filename else ".jpg"
        file_name = f"{ref_id}{ext}"
        file_path = abs_dir / file_name
        file_path.write_bytes(data)

        rel_path = str(rel_dir / file_name)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        ref = ImageRef(
            ref_id=ref_id,
            path=rel_path,
            sha256=sha,
            size_bytes=len(data),
            category=category,
            lot_id=lot_id,
            created_at=created_at,
        )

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                conn.execute(
                    """INSERT INTO images
                       (ref_id, path, sha256, size_bytes, category, lot_id,
                        product_code, line_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ref_id, rel_path, sha, len(data), category, lot_id,
                     product_code, line_id, created_at),
                )
                conn.commit()
            finally:
                conn.close()

        return ref

    def load(self, ref_id: str) -> bytes | None:
        """Load image bytes by reference ID."""
        row = self._get_meta(ref_id)
        if row is None:
            return None
        abs_path = self._root / row["path"]
        if abs_path.exists():
            return abs_path.read_bytes()
        # Try cloud fallback
        if self._cloud and row.get("cloud_key"):
            try:
                self._cloud.download(row["cloud_key"], abs_path)
                return abs_path.read_bytes()
            except Exception:
                pass
        return None

    def get_meta(self, ref_id: str) -> dict[str, Any] | None:
        """Get metadata for an image reference."""
        return self._get_meta(ref_id)

    def list_by_lot(self, lot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """List all images for a given lot."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM images WHERE lot_id = ? ORDER BY created_at DESC LIMIT ?",
                (lot_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def archive_old(self, max_age_days: int = 90) -> int:
        """
        Archive images older than max_age_days to cloud storage.
        Returns number of images archived.
        """
        if self._cloud is None:
            return 0
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(time.time() - max_age_days * 86400),
        )
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT ref_id, path FROM images WHERE archived = 0 AND created_at < ?",
                (cutoff,),
            ).fetchall()
            count = 0
            for ref_id, rel_path in rows:
                abs_path = self._root / rel_path
                if not abs_path.exists():
                    continue
                cloud_key = f"archive/{rel_path}"
                try:
                    self._cloud.upload(abs_path, cloud_key)
                    conn.execute(
                        "UPDATE images SET archived = 1, cloud_key = ? WHERE ref_id = ?",
                        (cloud_key, ref_id),
                    )
                    abs_path.unlink()
                    count += 1
                except Exception:
                    continue
            conn.commit()
            return count
        finally:
            conn.close()

    def cleanup(self, max_age_days: int = 180) -> int:
        """
        Delete images older than max_age_days (both local and DB records).
        Cloud copies are preserved. Returns number of records deleted.
        """
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(time.time() - max_age_days * 86400),
        )
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                rows = conn.execute(
                    "SELECT ref_id, path FROM images WHERE created_at < ?",
                    (cutoff,),
                ).fetchall()
                count = 0
                for ref_id, rel_path in rows:
                    abs_path = self._root / rel_path
                    if abs_path.exists():
                        abs_path.unlink(missing_ok=True)
                    conn.execute("DELETE FROM images WHERE ref_id = ?", (ref_id,))
                    count += 1
                conn.commit()
                return count
            finally:
                conn.close()

    def disk_usage(self) -> dict[str, Any]:
        """Return disk usage statistics."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM images"
            ).fetchone()
            archived = conn.execute(
                "SELECT COUNT(*) FROM images WHERE archived = 1"
            ).fetchone()
            return {
                "total_images": row[0],
                "total_bytes": row[1],
                "total_mb": round(row[1] / (1024 * 1024), 2),
                "archived_count": archived[0] if archived else 0,
                "root": str(self._root),
            }
        finally:
            conn.close()

    def _get_meta(self, ref_id: str) -> dict[str, Any] | None:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM images WHERE ref_id = ?", (ref_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
