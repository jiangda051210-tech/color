from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def init_innovation_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS innovation_customer_acceptance_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              customer_id TEXT NOT NULL,
              delta_e REAL NOT NULL,
              complained INTEGER NOT NULL,
              extra_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_innovation_acceptance_customer_time
            ON innovation_customer_acceptance_events(customer_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS innovation_customer_acceptance_models (
              customer_id TEXT PRIMARY KEY,
              updated_at TEXT NOT NULL,
              total_shipments INTEGER,
              total_complaints INTEGER,
              complaint_rate REAL,
              learned_threshold_50 REAL,
              safe_threshold_10 REAL,
              sensitivity TEXT,
              theta_json TEXT,
              profile_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS innovation_color_passports (
              passport_id TEXT PRIMARY KEY,
              lot_id TEXT,
              created_at TEXT NOT NULL,
              verification_hash TEXT,
              payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_innovation_passports_lot_time
            ON innovation_color_passports(lot_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS innovation_supplier_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              supplier_id TEXT NOT NULL,
              delta_e REAL NOT NULL,
              product TEXT,
              passed INTEGER NOT NULL,
              ts TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_innovation_supplier_id_time
            ON innovation_supplier_records(supplier_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS innovation_color_standards (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL,
              version INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              source TEXT,
              notes TEXT,
              lab_json TEXT NOT NULL,
              UNIQUE(code, version)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_innovation_standards_code_version
            ON innovation_color_standards(code, version)
            """
        )
        conn.commit()
    finally:
        conn.close()


def record_acceptance_event(
    db_path: Path,
    customer_id: str,
    delta_e: float,
    complained: bool,
    extra: dict[str, Any] | None = None,
) -> int:
    init_innovation_db(db_path)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            INSERT INTO innovation_customer_acceptance_events(
              created_at, customer_id, delta_e, complained, extra_json
            ) VALUES(?,?,?,?,?)
            """,
            (
                created_at,
                customer_id,
                float(delta_e),
                1 if bool(complained) else 0,
                json.dumps(extra or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def reload_customer_acceptance_from_db(
    db_path: Path,
    learner: Any,
    customer_id: str,
    limit: int = 10000,
) -> int:
    init_innovation_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT customer_id, delta_e, complained, extra_json
            FROM innovation_customer_acceptance_events
            WHERE customer_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (customer_id, max(1, int(limit))),
        ).fetchall()
    finally:
        conn.close()

    customers = getattr(learner, "_customers", None)
    if isinstance(customers, dict) and customer_id in customers:
        del customers[customer_id]

    loaded = 0
    for row in rows:
        extra_json = row["extra_json"] or "{}"
        try:
            extra = json.loads(extra_json)
            if not isinstance(extra, dict):
                extra = {}
        except Exception:  # noqa: BLE001
            extra = {}
        learner.record(
            customer_id=str(row["customer_id"]),
            delta_e=float(row["delta_e"]),
            complained=bool(int(row["complained"])),
            extra=extra,
        )
        loaded += 1
    return loaded


def upsert_acceptance_profile(db_path: Path, learner: Any, customer_id: str) -> dict[str, Any] | None:
    init_innovation_db(db_path)
    profile = learner.get_profile(customer_id)
    if not isinstance(profile, dict) or profile.get("status") == "unknown":
        return None

    theta = None
    customers = getattr(learner, "_customers", None)
    if isinstance(customers, dict):
        item = customers.get(customer_id, {})
        if isinstance(item, dict):
            theta = item.get("theta")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO innovation_customer_acceptance_models(
              customer_id, updated_at, total_shipments, total_complaints, complaint_rate,
              learned_threshold_50, safe_threshold_10, sensitivity, theta_json, profile_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(customer_id) DO UPDATE SET
              updated_at=excluded.updated_at,
              total_shipments=excluded.total_shipments,
              total_complaints=excluded.total_complaints,
              complaint_rate=excluded.complaint_rate,
              learned_threshold_50=excluded.learned_threshold_50,
              safe_threshold_10=excluded.safe_threshold_10,
              sensitivity=excluded.sensitivity,
              theta_json=excluded.theta_json,
              profile_json=excluded.profile_json
            """,
            (
                customer_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                int(profile.get("total_shipments", 0)),
                int(profile.get("total_complaints", 0)),
                float(profile.get("complaint_rate", 0.0)),
                float(profile.get("learned_threshold_50pct", 0.0)),
                float(profile.get("safe_threshold_10pct", 0.0)),
                str(profile.get("sensitivity", "")),
                json.dumps(theta if isinstance(theta, list) else [], ensure_ascii=False),
                json.dumps(profile, ensure_ascii=False),
            ),
        )
        conn.commit()
        return profile
    finally:
        conn.close()


def save_color_passport(db_path: Path, passport: dict[str, Any]) -> None:
    init_innovation_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO innovation_color_passports(
              passport_id, lot_id, created_at, verification_hash, payload_json
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(passport_id) DO UPDATE SET
              lot_id=excluded.lot_id,
              created_at=excluded.created_at,
              verification_hash=excluded.verification_hash,
              payload_json=excluded.payload_json
            """,
            (
                str(passport.get("passport_id", "")),
                str(passport.get("lot_id", "")),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                str(passport.get("verification_hash", "")),
                json.dumps(passport, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_color_passport(db_path: Path, passport_id: str) -> dict[str, Any] | None:
    init_innovation_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM innovation_color_passports
            WHERE passport_id = ?
            """,
            (passport_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def save_supplier_record(
    db_path: Path,
    supplier_id: str,
    delta_e: float,
    product: str = "",
    passed: bool = True,
    ts: str | None = None,
) -> int:
    init_innovation_db(db_path)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            INSERT INTO innovation_supplier_records(
              created_at, supplier_id, delta_e, product, passed, ts
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                created_at,
                str(supplier_id),
                float(delta_e),
                str(product or ""),
                1 if bool(passed) else 0,
                str(ts) if ts else created_at,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def load_supplier_records(
    db_path: Path,
    supplier_id: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    init_innovation_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if supplier_id:
            rows = conn.execute(
                """
                SELECT supplier_id, delta_e, product, passed, ts
                FROM innovation_supplier_records
                WHERE supplier_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (supplier_id, max(1, int(limit))),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT supplier_id, delta_e, product, passed, ts
                FROM innovation_supplier_records
                ORDER BY id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "supplier_id": str(row["supplier_id"]),
                "delta_e": float(row["delta_e"]),
                "product": str(row["product"] or ""),
                "passed": bool(int(row["passed"])),
                "ts": str(row["ts"] or ""),
            }
        )
    return out


def next_standard_version(db_path: Path, code: str) -> int:
    init_innovation_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(version), 0)
            FROM innovation_color_standards
            WHERE code = ?
            """,
            (str(code),),
        ).fetchone()
    finally:
        conn.close()
    current = int(row[0]) if row and row[0] is not None else 0
    return current + 1


def save_standard_version(
    db_path: Path,
    code: str,
    version: int,
    lab: dict[str, Any],
    source: str = "manual",
    notes: str = "",
    created_at: str | None = None,
) -> None:
    init_innovation_db(db_path)
    created = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "L": float(lab.get("L", 0.0)),
        "a": float(lab.get("a", 0.0)),
        "b": float(lab.get("b", 0.0)),
    }
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO innovation_color_standards(
              code, version, created_at, source, notes, lab_json
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(code, version) DO UPDATE SET
              created_at=excluded.created_at,
              source=excluded.source,
              notes=excluded.notes,
              lab_json=excluded.lab_json
            """,
            (
                str(code),
                int(version),
                created,
                str(source or ""),
                str(notes or ""),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_standard_versions(
    db_path: Path,
    code: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    init_innovation_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if code:
            rows = conn.execute(
                """
                SELECT code, version, created_at, source, notes, lab_json
                FROM innovation_color_standards
                WHERE code = ?
                ORDER BY code ASC, version ASC
                LIMIT ?
                """,
                (str(code), max(1, int(limit))),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT code, version, created_at, source, notes, lab_json
                FROM innovation_color_standards
                ORDER BY code ASC, version ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            lab = json.loads(row["lab_json"] or "{}")
        except Exception:  # noqa: BLE001
            lab = {}
        if not isinstance(lab, dict):
            lab = {}
        out.append(
            {
                "code": str(row["code"]),
                "version": int(row["version"]),
                "created_at": str(row["created_at"]),
                "source": str(row["source"] or ""),
                "notes": str(row["notes"] or ""),
                "lab": {
                    "L": float(lab.get("L", 0.0)),
                    "a": float(lab.get("a", 0.0)),
                    "b": float(lab.get("b", 0.0)),
                },
            }
        )
    return out
