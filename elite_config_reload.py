"""
Hot-reloadable configuration for SENIA Elite policy files.

Watches JSON policy files and reloads them when modified, without
requiring a service restart. Thread-safe.

Usage:
    store = ConfigStore()
    store.register("decision_policy", Path("decision_policy.default.json"))
    store.register("customer_tier", Path("customer_tier_policy.default.json"))

    # Get current config (automatically reloads if file changed)
    policy = store.get("decision_policy")

    # Force reload
    store.reload("decision_policy")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass
class _ConfigEntry:
    path: Path
    data: dict[str, Any] = field(default_factory=dict)
    last_mtime: float = 0.0
    last_check: float = 0.0
    check_interval_sec: float = 2.0
    load_error: str | None = None


class ConfigStore:
    """Thread-safe, auto-reloading configuration store."""

    def __init__(self, check_interval_sec: float = 2.0) -> None:
        self._entries: dict[str, _ConfigEntry] = {}
        self._lock = RLock()
        self._check_interval = check_interval_sec
        self._reload_callbacks: dict[str, list[Any]] = {}

    def register(self, name: str, path: Path) -> None:
        """Register a JSON config file for auto-reload tracking."""
        with self._lock:
            entry = _ConfigEntry(
                path=path,
                check_interval_sec=self._check_interval,
            )
            self._entries[name] = entry
            self._load_entry(entry)

    def get(self, name: str) -> dict[str, Any]:
        """Get current config, auto-reloading if the file changed."""
        with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                return {}
            now = time.monotonic()
            if now - entry.last_check >= entry.check_interval_sec:
                entry.last_check = now
                self._maybe_reload(name, entry)
            return entry.data

    def reload(self, name: str) -> dict[str, Any]:
        """Force reload a config and return the new data."""
        with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                return {}
            self._load_entry(entry)
            self._fire_callbacks(name, entry.data)
            return entry.data

    def reload_all(self) -> None:
        """Force reload all registered configs."""
        with self._lock:
            for name in list(self._entries):
                self.reload(name)

    def on_reload(self, name: str, callback: Any) -> None:
        """Register a callback invoked after a successful reload."""
        with self._lock:
            self._reload_callbacks.setdefault(name, []).append(callback)

    def status(self) -> dict[str, Any]:
        """Return status of all registered configs."""
        with self._lock:
            return {
                name: {
                    "path": str(entry.path),
                    "loaded": entry.load_error is None,
                    "error": entry.load_error,
                    "last_mtime": entry.last_mtime,
                }
                for name, entry in self._entries.items()
            }

    # --- internal ---

    def _load_entry(self, entry: _ConfigEntry) -> None:
        try:
            raw = entry.path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            if not isinstance(data, dict):
                entry.load_error = "config root must be a JSON object"
                return
            entry.data = data
            entry.load_error = None
            entry.last_mtime = entry.path.stat().st_mtime
        except FileNotFoundError:
            entry.load_error = f"file not found: {entry.path}"
        except (json.JSONDecodeError, ValueError) as exc:
            entry.load_error = f"JSON parse error: {exc}"
        except OSError as exc:
            entry.load_error = f"read error: {exc}"

    def _maybe_reload(self, name: str, entry: _ConfigEntry) -> None:
        try:
            mtime = entry.path.stat().st_mtime
        except OSError:
            return
        if mtime != entry.last_mtime:
            self._load_entry(entry)
            if entry.load_error is None:
                self._fire_callbacks(name, entry.data)

    def _fire_callbacks(self, name: str, data: dict[str, Any]) -> None:
        for cb in self._reload_callbacks.get(name, []):
            try:
                cb(data)
            except Exception:  # noqa: BLE001 - callbacks must not crash the store
                pass
