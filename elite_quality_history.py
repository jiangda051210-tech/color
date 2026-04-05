from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np


def _mann_kendall(x: np.ndarray) -> dict[str, Any]:
    """Simple Mann-Kendall trend test implementation.

    Returns S statistic, normalised Tau, variance, z-score, and two-sided p-value.
    Works for n >= 3.  For ties the basic variance formula is used (no tie correction).
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n < 3:
        return {"S": 0, "tau": 0.0, "z": 0.0, "p": 1.0, "trend": "no_data"}

    s = 0
    for k in range(n - 1):
        for j in range(k + 1, n):
            diff = x[j] - x[k]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    n_pairs = n * (n - 1) / 2.0
    tau = s / n_pairs if n_pairs > 0 else 0.0

    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    std_s = math.sqrt(var_s) if var_s > 0 else 1e-12

    if s > 0:
        z = (s - 1) / std_s
    elif s < 0:
        z = (s + 1) / std_s
    else:
        z = 0.0

    # Two-sided p-value via normal approximation
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))

    if p < 0.05:
        trend = "increasing" if s > 0 else "decreasing"
    else:
        trend = "no_trend"

    return {"S": int(s), "tau": round(tau, 4), "z": round(z, 4), "p": round(p, 4), "trend": trend}


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing_names = {str(row[1]) for row in existing}
    for name, sql_type in columns.items():
        if name in existing_names:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              mode TEXT NOT NULL,
              profile TEXT NOT NULL,
              line_id TEXT,
              product_code TEXT,
              lot_id TEXT,
              pass INTEGER NOT NULL,
              confidence REAL,
              avg_de REAL,
              p95_de REAL,
              max_de REAL,
              dL REAL,
              dC REAL,
              dH REAL,
              report_path TEXT,
              decision_code TEXT,
              decision_priority TEXT,
              decision_risk REAL,
              estimated_cost REAL,
              customer_score REAL,
              boss_score REAL,
              company_score REAL
            )
            """
        )
        _ensure_columns(
            conn,
            "quality_runs",
            {
                "decision_code": "TEXT",
                "decision_priority": "TEXT",
                "decision_risk": "REAL",
                "estimated_cost": "REAL",
                "customer_score": "REAL",
                "boss_score": "REAL",
                "company_score": "REAL",
            },
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_quality_runs_line_product_time
            ON quality_runs(line_id, product_code, created_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_outcomes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              run_id INTEGER,
              report_path TEXT,
              line_id TEXT,
              product_code TEXT,
              lot_id TEXT,
              decision_code TEXT,
              predicted_risk REAL,
              outcome TEXT NOT NULL,
              severity REAL,
              realized_cost REAL,
              customer_rating REAL,
              note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_quality_outcomes_line_product_time
            ON quality_outcomes(line_id, product_code, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_quality_outcomes_run_id
            ON quality_outcomes(run_id)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def extract_metrics(report: dict[str, Any]) -> dict[str, float]:
    result = report.get("result", {})
    summary = result.get("summary", {})
    confidence = result.get("confidence", {})
    mode = str(report.get("mode", "unknown"))

    if mode == "ensemble_single":
        avg_de = _to_float(summary.get("median_avg_delta_e00"), np.nan)
        p95_de = _to_float(summary.get("median_p95_delta_e00"), np.nan)
        max_de = _to_float(summary.get("median_max_delta_e00"), np.nan)
        d_l = _to_float(summary.get("median_dL"), np.nan)
        d_c = _to_float(summary.get("median_dC"), np.nan)
        d_h = _to_float(summary.get("median_dH_deg"), np.nan)
        conf = _to_float(confidence.get("median"), np.nan)
    else:
        avg_de = _to_float(summary.get("avg_delta_e00"), np.nan)
        p95_de = _to_float(summary.get("p95_delta_e00"), np.nan)
        max_de = _to_float(summary.get("max_delta_e00"), np.nan)
        d_l = _to_float(summary.get("dL"), np.nan)
        d_c = _to_float(summary.get("dC"), np.nan)
        d_h = _to_float(summary.get("dH_deg"), np.nan)
        conf = _to_float(confidence.get("overall"), np.nan)

    return {
        "avg_de": avg_de,
        "p95_de": p95_de,
        "max_de": max_de,
        "dL": d_l,
        "dC": d_c,
        "dH": d_h,
        "confidence": conf,
    }


def record_run(
    db_path: Path,
    report: dict[str, Any],
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    report_path: str | None = None,
) -> None:
    metrics = extract_metrics(report)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = str(report.get("mode", "unknown"))
    profile = str(report.get("profile", {}).get("used", "unknown"))
    passed = 1 if bool(report.get("result", {}).get("pass", False)) else 0
    decision_center = report.get("decision_center", {})
    decision_code = str(decision_center.get("decision_code", "")) if isinstance(decision_center, dict) else ""
    decision_priority = str(decision_center.get("priority", "")) if isinstance(decision_center, dict) else ""
    decision_risk = _to_float(decision_center.get("risk_probability"), np.nan) if isinstance(decision_center, dict) else np.nan
    estimated_cost = _to_float(decision_center.get("estimated_cost"), np.nan) if isinstance(decision_center, dict) else np.nan
    scores = decision_center.get("stakeholder_scores", {}) if isinstance(decision_center, dict) else {}
    customer_score = _to_float(scores.get("customer_score"), np.nan) if isinstance(scores, dict) else np.nan
    boss_score = _to_float(scores.get("boss_score"), np.nan) if isinstance(scores, dict) else np.nan
    company_score = _to_float(scores.get("company_score"), np.nan) if isinstance(scores, dict) else np.nan

    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO quality_runs(
              created_at, mode, profile, line_id, product_code, lot_id,
              pass, confidence, avg_de, p95_de, max_de, dL, dC, dH, report_path,
              decision_code, decision_priority, decision_risk, estimated_cost,
              customer_score, boss_score, company_score
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                created_at,
                mode,
                profile,
                line_id,
                product_code,
                lot_id,
                passed,
                metrics["confidence"],
                metrics["avg_de"],
                metrics["p95_de"],
                metrics["max_de"],
                metrics["dL"],
                metrics["dC"],
                metrics["dH"],
                report_path,
                decision_code,
                decision_priority,
                decision_risk,
                estimated_cost,
                customer_score,
                boss_score,
                company_score,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recent_stats(
    db_path: Path,
    line_id: str,
    product_code: str,
    window: int = 30,
) -> dict[str, Any]:
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT avg_de, p95_de, max_de, confidence
            FROM quality_runs
            WHERE line_id = ? AND product_code = ?
            AND avg_de IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (line_id, product_code, int(max(1, window))),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"count": 0}

    arr = np.array(rows, dtype=np.float64)
    # Rows come ORDER BY id DESC (newest first); reverse to ascending time order
    arr = arr[::-1]
    avg = arr[:, 0]
    p95 = arr[:, 1]
    maxv = arr[:, 2]
    conf = arr[:, 3]

    # polyfit on ascending-time data: x[0]=oldest, x[-1]=newest
    x = np.arange(len(avg), dtype=np.float64)
    slope = 0.0
    if len(avg) >= 4 and np.std(avg) > 1e-8:
        slope = float(np.polyfit(x, avg, 1)[0])

    # Mann-Kendall trend test for robust trend detection
    mk_result = _mann_kendall(avg)

    # Also compute std for p95 and max for z-score use downstream
    return {
        "count": int(len(avg)),
        "avg_mean": float(np.mean(avg)),
        "avg_std": float(np.std(avg)),
        "avg_p95": float(np.percentile(avg, 95)),
        "p95_mean": float(np.mean(p95)),
        "p95_std": float(np.std(p95)),
        "max_mean": float(np.mean(maxv)),
        "max_std": float(np.std(maxv)),
        "conf_mean": float(np.mean(conf)),
        "conf_std": float(np.std(conf)),
        "avg_slope_per_run": slope,
        "mann_kendall": mk_result,
    }


def assess_current_vs_history(
    db_path: Path,
    report: dict[str, Any],
    line_id: str | None,
    product_code: str | None,
    window: int = 30,
) -> dict[str, Any]:
    if not line_id or not product_code:
        return {"enabled": False, "reason": "line_or_product_missing"}

    stats = recent_stats(db_path=db_path, line_id=line_id, product_code=product_code, window=window)
    if stats.get("count", 0) < 5:
        return {"enabled": True, "history_count": int(stats.get("count", 0)), "flags": [], "stats": stats}

    m = extract_metrics(report)
    flags: list[str] = []

    # Consistent z-score approach across all metrics: flag when current > mean + k*std
    k_high = 2.2  # z-score threshold for "outlier high"
    k_conf = 2.0  # z-score threshold for confidence drop (lower tail)

    avg_mean = stats["avg_mean"]
    avg_std = max(1e-6, stats["avg_std"])
    p95_mean = stats["p95_mean"]
    p95_std = max(1e-6, stats.get("p95_std", avg_std))
    max_mean = stats["max_mean"]
    max_std = max(1e-6, stats.get("max_std", avg_std))
    conf_mean = stats["conf_mean"]
    conf_std = max(1e-6, stats.get("conf_std", 0.05))

    z_avg = (m["avg_de"] - avg_mean) / avg_std
    z_p95 = (m["p95_de"] - p95_mean) / p95_std
    z_max = (m["max_de"] - max_mean) / max_std
    z_conf = (conf_mean - m["confidence"]) / conf_std  # positive = current is worse

    if z_avg > k_high:
        flags.append("history_avg_outlier_high")
    if z_p95 > k_high:
        flags.append("history_p95_outlier_high")
    if z_max > k_high:
        flags.append("history_max_outlier_high")
    if z_conf > k_conf:
        flags.append("history_confidence_drop")

    # Use Mann-Kendall if available for more robust trend detection
    mk = stats.get("mann_kendall", {})
    if mk.get("trend") == "increasing" and mk.get("p", 1.0) < 0.05:
        flags.append("history_drift_uptrend")
    elif stats["avg_slope_per_run"] > 0.03:
        # Fallback to slope-based detection
        flags.append("history_drift_uptrend")

    return {
        "enabled": True,
        "history_count": int(stats["count"]),
        "flags": flags,
        "z_scores": {
            "avg_de": round(z_avg, 3),
            "p95_de": round(z_p95, 3),
            "max_de": round(z_max, 3),
            "confidence": round(z_conf, 3),
        },
        "stats": stats,
        "current": m,
    }


def list_recent_runs(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    init_db(db_path)
    query = """
        SELECT
          id, created_at, mode, profile, line_id, product_code, lot_id,
          pass, confidence, avg_de, p95_de, max_de, dL, dC, dH, report_path,
          decision_code, decision_priority, decision_risk, estimated_cost,
          customer_score, boss_score, company_score
        FROM quality_runs
    """
    clauses: list[str] = []
    params: list[Any] = []
    if line_id:
        clauses.append("line_id = ?")
        params.append(line_id)
    if product_code:
        clauses.append("product_code = ?")
        params.append(product_code)
    if lot_id:
        clauses.append("lot_id = ?")
        params.append(lot_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(max(1, limit)))

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(query, tuple(params)).fetchall()
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": int(row[0]),
                "created_at": str(row[1]),
                "mode": str(row[2]),
                "profile": str(row[3]),
                "line_id": row[4],
                "product_code": row[5],
                "lot_id": row[6],
                "pass": bool(row[7]),
                "confidence": None if row[8] is None else float(row[8]),
                "avg_de": None if row[9] is None else float(row[9]),
                "p95_de": None if row[10] is None else float(row[10]),
                "max_de": None if row[11] is None else float(row[11]),
                "dL": None if row[12] is None else float(row[12]),
                "dC": None if row[13] is None else float(row[13]),
                "dH": None if row[14] is None else float(row[14]),
                "report_path": row[15],
                "decision_code": row[16],
                "decision_priority": row[17],
                "decision_risk": None if row[18] is None else float(row[18]),
                "estimated_cost": None if row[19] is None else float(row[19]),
                "customer_score": None if row[20] is None else float(row[20]),
                "boss_score": None if row[21] is None else float(row[21]),
                "company_score": None if row[22] is None else float(row[22]),
            }
        )
    return result


def history_overview(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(1, int(window)),
    )
    if not runs:
        return {"count": 0, "pass_rate": None, "latest_created_at": None}

    pass_rate = float(np.mean([1.0 if r.get("pass") else 0.0 for r in runs]))
    conf = np.array([_to_float(r.get("confidence"), np.nan) for r in runs], dtype=np.float64)
    avg_de = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs], dtype=np.float64)
    p95_de = np.array([_to_float(r.get("p95_de"), np.nan) for r in runs], dtype=np.float64)

    return {
        "count": int(len(runs)),
        "pass_rate": pass_rate,
        "latest_created_at": runs[0].get("created_at"),
        "confidence_mean": float(np.nanmean(conf)),
        "avg_de_mean": float(np.nanmean(avg_de)),
        "avg_de_p95": float(np.nanpercentile(avg_de, 95)),
        "p95_de_mean": float(np.nanmean(p95_de)),
    }


def executive_kpis(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(1, int(window)),
    )
    if not runs:
        return {"count": 0}

    decision_codes = [str(r.get("decision_code") or "") for r in runs]
    valid_codes = [c for c in decision_codes if c]
    scored = [r for r in runs if r.get("customer_score") is not None]
    decision_counts: dict[str, int] = {}
    for code in decision_codes:
        if not code:
            continue
        decision_counts[code] = decision_counts.get(code, 0) + 1

    if valid_codes:
        auto_rate = float(np.mean([1.0 if c == "AUTO_RELEASE" else 0.0 for c in valid_codes]))
        manual_rate = float(np.mean([1.0 if c == "MANUAL_REVIEW" else 0.0 for c in valid_codes]))
        recapture_rate = float(np.mean([1.0 if c == "RECAPTURE_REQUIRED" else 0.0 for c in valid_codes]))
        hold_rate = float(np.mean([1.0 if c == "HOLD_AND_ESCALATE" else 0.0 for c in valid_codes]))
    else:
        auto_rate = 0.0
        manual_rate = 0.0
        recapture_rate = 0.0
        hold_rate = 0.0

    customer = np.array([_to_float(r.get("customer_score"), np.nan) for r in scored], dtype=np.float64)
    boss = np.array([_to_float(r.get("boss_score"), np.nan) for r in scored], dtype=np.float64)
    company = np.array([_to_float(r.get("company_score"), np.nan) for r in scored], dtype=np.float64)
    est_cost = np.array([_to_float(r.get("estimated_cost"), np.nan) for r in runs], dtype=np.float64)

    return {
        "count": int(len(runs)),
        "latest_created_at": runs[0].get("created_at"),
        "decision_counts": decision_counts,
        "auto_release_rate": auto_rate,
        "manual_review_rate": manual_rate,
        "recapture_rate": recapture_rate,
        "hold_rate": hold_rate,
        "customer_acceptance_index": float(np.nanmean(customer)) if customer.size else None,
        "boss_efficiency_index": float(np.nanmean(boss)) if boss.size else None,
        "company_governance_index": float(np.nanmean(company)) if company.size else None,
        "estimated_cost_total": float(np.nansum(est_cost)),
        "estimated_cost_mean": float(np.nanmean(est_cost)) if est_cost.size else None,
    }


def _fetch_run_meta(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, report_path, line_id, product_code, lot_id, decision_code, decision_risk
        FROM quality_runs
        WHERE id = ?
        """,
        (int(run_id),),
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "report_path": row[1],
        "line_id": row[2],
        "product_code": row[3],
        "lot_id": row[4],
        "decision_code": row[5],
        "decision_risk": None if row[6] is None else float(row[6]),
    }


def _find_run_by_report_path(conn: sqlite3.Connection, report_path: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, report_path, line_id, product_code, lot_id, decision_code, decision_risk
        FROM quality_runs
        WHERE report_path = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(report_path),),
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "report_path": row[1],
        "line_id": row[2],
        "product_code": row[3],
        "lot_id": row[4],
        "decision_code": row[5],
        "decision_risk": None if row[6] is None else float(row[6]),
    }


def record_outcome(
    db_path: Path,
    outcome: str,
    run_id: int | None = None,
    report_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    severity: float | None = None,
    realized_cost: float | None = None,
    customer_rating: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    normalized_outcome = str(outcome).strip().lower()
    allowed = {"accepted", "complaint_minor", "complaint_major", "return", "rework", "pending"}
    if normalized_outcome not in allowed:
        raise ValueError(f"unsupported outcome: {outcome}")

    conn = sqlite3.connect(str(db_path))
    try:
        run_meta = None
        if run_id is not None:
            run_meta = _fetch_run_meta(conn, int(run_id))
        elif report_path:
            run_meta = _find_run_by_report_path(conn, str(report_path))

        resolved_run_id = int(run_meta["id"]) if run_meta else None
        resolved_report_path = str(report_path or (run_meta.get("report_path") if run_meta else "") or "")
        resolved_line_id = line_id or (run_meta.get("line_id") if run_meta else None)
        resolved_product_code = product_code or (run_meta.get("product_code") if run_meta else None)
        resolved_lot_id = lot_id or (run_meta.get("lot_id") if run_meta else None)
        decision_code = str(run_meta.get("decision_code") or "") if run_meta else ""
        predicted_risk = run_meta.get("decision_risk") if run_meta else None

        conn.execute(
            """
            INSERT INTO quality_outcomes(
              created_at, run_id, report_path, line_id, product_code, lot_id,
              decision_code, predicted_risk, outcome, severity, realized_cost,
              customer_rating, note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now,
                resolved_run_id,
                resolved_report_path if resolved_report_path else None,
                resolved_line_id,
                resolved_product_code,
                resolved_lot_id,
                decision_code if decision_code else None,
                None if predicted_risk is None else float(predicted_risk),
                normalized_outcome,
                None if severity is None else float(severity),
                None if realized_cost is None else float(realized_cost),
                None if customer_rating is None else float(customer_rating),
                note,
            ),
        )
        out_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
    finally:
        conn.close()

    return {
        "id": out_id,
        "created_at": now,
        "run_id": resolved_run_id,
        "report_path": resolved_report_path if resolved_report_path else None,
        "line_id": resolved_line_id,
        "product_code": resolved_product_code,
        "lot_id": resolved_lot_id,
        "decision_code": decision_code if decision_code else None,
        "predicted_risk": predicted_risk,
        "outcome": normalized_outcome,
    }


def list_outcomes(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    init_db(db_path)
    query = """
        SELECT
          id, created_at, run_id, report_path, line_id, product_code, lot_id,
          decision_code, predicted_risk, outcome, severity, realized_cost,
          customer_rating, note
        FROM quality_outcomes
    """
    clauses: list[str] = []
    params: list[Any] = []
    if line_id:
        clauses.append("line_id = ?")
        params.append(line_id)
    if product_code:
        clauses.append("product_code = ?")
        params.append(product_code)
    if lot_id:
        clauses.append("lot_id = ?")
        params.append(lot_id)
    if outcome:
        clauses.append("outcome = ?")
        params.append(str(outcome).strip().lower())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(max(1, limit)))

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(query, tuple(params)).fetchall()
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": int(row[0]),
                "created_at": str(row[1]),
                "run_id": None if row[2] is None else int(row[2]),
                "report_path": row[3],
                "line_id": row[4],
                "product_code": row[5],
                "lot_id": row[6],
                "decision_code": row[7],
                "predicted_risk": None if row[8] is None else float(row[8]),
                "outcome": row[9],
                "severity": None if row[10] is None else float(row[10]),
                "realized_cost": None if row[11] is None else float(row[11]),
                "customer_rating": None if row[12] is None else float(row[12]),
                "note": row[13],
            }
        )
    return result


def outcome_kpis(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    rows = list_outcomes(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(1, int(window)),
    )
    if not rows:
        return {"count": 0}

    outcomes = [str(r.get("outcome") or "") for r in rows]
    accepted = float(np.mean([1.0 if o == "accepted" else 0.0 for o in outcomes]))
    complaint = float(np.mean([1.0 if o in ("complaint_minor", "complaint_major") else 0.0 for o in outcomes]))
    escape = float(np.mean([1.0 if o in ("complaint_major", "return") else 0.0 for o in outcomes]))
    rework = float(np.mean([1.0 if o == "rework" else 0.0 for o in outcomes]))
    auto_rows = [r for r in rows if str(r.get("decision_code") or "") == "AUTO_RELEASE"]
    if auto_rows:
        auto_escape = float(
            np.mean(
                [
                    1.0 if str(r.get("outcome") or "") in ("complaint_major", "return") else 0.0
                    for r in auto_rows
                ]
            )
        )
    else:
        auto_escape = 0.0

    ratings = np.array([_to_float(r.get("customer_rating"), np.nan) for r in rows], dtype=np.float64)
    costs = np.array([_to_float(r.get("realized_cost"), np.nan) for r in rows], dtype=np.float64)

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o] = counts.get(o, 0) + 1

    return {
        "count": int(len(rows)),
        "latest_created_at": rows[0].get("created_at"),
        "outcome_counts": counts,
        "accepted_rate": accepted,
        "complaint_rate": complaint,
        "escape_rate": escape,
        "rework_rate": rework,
        "auto_release_escape_rate": auto_escape,
        "customer_rating_mean": float(np.nanmean(ratings)) if ratings.size else None,
        "realized_cost_total": float(np.nansum(costs)),
        "realized_cost_mean": float(np.nanmean(costs)) if costs.size else None,
    }


def recommend_policy_adjustments(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    kpi = outcome_kpis(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(1, int(window)),
    )
    if kpi.get("count", 0) < 8:
        return {
            "enabled": True,
            "window": int(window),
            "insufficient_data": True,
            "recommendations": [],
            "policy_patch": {},
            "kpis": kpi,
            "message": "Not enough closed-loop outcomes yet; keep current policy and collect more data.",
        }

    auto_escape = _to_float(kpi.get("auto_release_escape_rate"), 0.0)
    accepted_rate = _to_float(kpi.get("accepted_rate"), 0.0)
    complaint_rate = _to_float(kpi.get("complaint_rate"), 0.0)
    rating_mean = _to_float(kpi.get("customer_rating_mean"), np.nan)

    recs: list[str] = []
    patch: dict[str, Any] = {"decision_policy": {}}
    confidence_adj = 0.0
    avg_ratio_adj = 0.0
    p95_ratio_adj = 0.0

    if auto_escape > 0.03:
        confidence_adj += 0.03
        avg_ratio_adj -= 0.03
        p95_ratio_adj -= 0.03
        recs.append("Auto-release escape rate is high; tighten confidence and color-ratio gates.")
    elif auto_escape < 0.01 and accepted_rate > 0.94 and complaint_rate < 0.03:
        confidence_adj -= 0.01
        avg_ratio_adj += 0.01
        p95_ratio_adj += 0.01
        recs.append("Escape rate is low and acceptance is high; policy can be slightly relaxed for throughput.")

    if not np.isnan(rating_mean):
        if rating_mean < 78:
            confidence_adj += 0.02
            recs.append("Customer rating is below target; tighten release policy.")
        elif rating_mean > 90 and auto_escape < 0.01:
            confidence_adj -= 0.005
            recs.append("Customer rating is excellent; allow marginally higher automation.")

    if abs(confidence_adj) > 1e-6:
        patch["decision_policy"]["auto_release_min_confidence_delta"] = round(confidence_adj, 4)
    if abs(avg_ratio_adj) > 1e-6:
        patch["decision_policy"]["max_avg_ratio_for_auto_release_delta"] = round(avg_ratio_adj, 4)
    if abs(p95_ratio_adj) > 1e-6:
        patch["decision_policy"]["max_p95_ratio_for_auto_release_delta"] = round(p95_ratio_adj, 4)

    return {
        "enabled": True,
        "window": int(window),
        "insufficient_data": False,
        "recommendations": recs,
        "policy_patch": patch if patch.get("decision_policy") else {},
        "kpis": kpi,
    }


def _parse_time(text: Any) -> datetime | None:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def complaint_early_warning(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 300,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(50, int(window)),
    )
    outcomes = list_outcomes(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(80, int(window)),
    )
    if not runs:
        return {"enabled": False, "reason": "no_runs"}

    now = datetime.now()
    t7 = now - timedelta(days=7)
    t30 = now - timedelta(days=30)

    def in_range(row: dict[str, Any], threshold: datetime) -> bool:
        ts = _parse_time(row.get("created_at"))
        return ts is not None and ts >= threshold

    runs7 = [r for r in runs if in_range(r, t7)]
    runs30 = [r for r in runs if in_range(r, t30)]
    out30 = [o for o in outcomes if in_range(o, t30)]

    if not runs30:
        runs30 = runs[: min(30, len(runs))]

    avg7 = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs7], dtype=np.float64)
    avg30 = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs30], dtype=np.float64)
    conf7 = np.array([_to_float(r.get("confidence"), np.nan) for r in runs7], dtype=np.float64)
    conf30 = np.array([_to_float(r.get("confidence"), np.nan) for r in runs30], dtype=np.float64)
    risk7 = np.array([_to_float(r.get("decision_risk"), np.nan) for r in runs7], dtype=np.float64)
    hold7 = np.array([1.0 if str(r.get("decision_code") or "") == "HOLD_AND_ESCALATE" else 0.0 for r in runs7], dtype=np.float64)

    avg7_m = float(np.nanmean(avg7)) if avg7.size else float(np.nanmean(avg30))
    avg30_m = float(np.nanmean(avg30)) if avg30.size else max(1e-6, avg7_m)
    conf7_m = float(np.nanmean(conf7)) if conf7.size else float(np.nanmean(conf30))
    conf30_m = float(np.nanmean(conf30)) if conf30.size else max(1e-6, conf7_m)
    risk7_m = float(np.nanmean(risk7)) if risk7.size else 0.0
    hold7_r = float(np.nanmean(hold7)) if hold7.size else 0.0

    outcomes30 = [str(o.get("outcome") or "") for o in out30]
    complaint30 = float(np.mean([1.0 if x in ("complaint_minor", "complaint_major") else 0.0 for x in outcomes30])) if outcomes30 else 0.0
    escape30 = float(np.mean([1.0 if x in ("complaint_major", "return") else 0.0 for x in outcomes30])) if outcomes30 else 0.0

    slope = 0.0
    avg_seq = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs[: min(40, len(runs))]], dtype=np.float64)
    avg_seq = avg_seq[~np.isnan(avg_seq)]
    if avg_seq.size >= 5 and np.std(avg_seq) > 1e-8:
        x = np.arange(avg_seq.size, dtype=np.float64)
        slope = float(np.polyfit(x, avg_seq[::-1], 1)[0])

    uplift_avg = max(0.0, avg7_m / max(1e-6, avg30_m) - 1.0)
    conf_drop = max(0.0, conf30_m - conf7_m)
    slope_pos = max(0.0, slope)

    # --- Proper normalization: each raw driver to [0, 1] before scaling ---
    # Saturation points (beyond which the driver is at max contribution)
    _sat_uplift = 0.5        # 50% uplift saturates
    _sat_conf_drop = 0.15    # 15-point confidence drop saturates
    _sat_risk = 0.8          # risk_probability near 0.8 saturates
    _sat_hold = 0.5          # 50% hold rate saturates
    _sat_complaint = 0.15    # 15% complaint rate saturates
    _sat_escape = 0.10       # 10% escape rate saturates
    _sat_slope = 0.08        # slope of 0.08 ΔE/run saturates

    norm_uplift = min(uplift_avg / _sat_uplift, 1.0)
    norm_conf_drop = min(conf_drop / _sat_conf_drop, 1.0)
    norm_risk = min(max(0.0, risk7_m) / _sat_risk, 1.0)
    norm_hold = min(hold7_r / _sat_hold, 1.0)
    norm_complaint = min(complaint30 / _sat_complaint, 1.0)
    norm_escape = min(escape30 / _sat_escape, 1.0)
    norm_slope = min(slope_pos / _sat_slope, 1.0)

    # Weights (sum to 100 so final score is 0-100)
    drivers_raw = {
        "avg_deltae_uplift": norm_uplift,
        "confidence_drop": norm_conf_drop,
        "recent_decision_risk": norm_risk,
        "recent_hold_rate": norm_hold,
        "recent_complaint_rate": norm_complaint,
        "recent_escape_rate": norm_escape,
        "avg_trend_slope": norm_slope,
    }
    driver_weights = {
        "avg_deltae_uplift": 16.0,
        "confidence_drop": 18.0,
        "recent_decision_risk": 13.0,
        "recent_hold_rate": 11.0,
        "recent_complaint_rate": 16.0,
        "recent_escape_rate": 16.0,
        "avg_trend_slope": 10.0,
    }
    drivers = {k: driver_weights[k] * drivers_raw[k] for k in drivers_raw}
    score = float(np.clip(sum(drivers.values()), 0.0, 100.0))

    # Convert to near-term probabilities with conservative floor.
    p7 = float(np.clip(0.01 + 0.58 * (score / 100.0) + 0.35 * complaint30, 0.0, 0.95))
    p30 = float(np.clip(0.03 + 0.72 * (score / 100.0) + 0.45 * complaint30, 0.0, 0.98))

    # --- Confidence intervals on early warning probability ---
    # Use a simple logit-normal approximation: CI width scales with data sparsity
    n_data = max(len(runs7), 1)
    se_factor = 1.96 / math.sqrt(n_data)  # 95% CI
    p7_lo = float(np.clip(p7 - se_factor * p7 * (1 - p7), 0.0, 1.0))
    p7_hi = float(np.clip(p7 + se_factor * p7 * (1 - p7), 0.0, 1.0))
    p30_lo = float(np.clip(p30 - se_factor * p30 * (1 - p30), 0.0, 1.0))
    p30_hi = float(np.clip(p30 + se_factor * p30 * (1 - p30), 0.0, 1.0))

    if score >= 70:
        level = "red"
    elif score >= 52:
        level = "orange"
    elif score >= 32:
        level = "yellow"
    else:
        level = "green"

    top_drivers = sorted(drivers.items(), key=lambda kv: kv[1], reverse=True)[:4]

    recommendations: list[str] = []
    if level in ("orange", "red"):
        recommendations.append("Switch current line to stricter customer policy immediately.")
        recommendations.append("Raise manual review and recapture sampling for next 3 days.")
    if conf_drop > 0.05:
        recommendations.append("Confidence dropped significantly; check lighting and camera cleanliness.")
    if uplift_avg > 0.12:
        recommendations.append("Avg DeltaE increased sharply; verify raw material lot and process settings.")
    if complaint30 > 0.05:
        recommendations.append("Recent complaint rate is high; prioritize VIP-grade thresholds.")
    if not recommendations:
        recommendations.append("Risk is currently controlled; keep policy stable and monitor daily.")

    return {
        "enabled": True,
        "warning_level": level,
        "risk_index_0_100": score,
        "forecast": {
            "complaint_probability_7d": p7,
            "complaint_probability_30d": p30,
        },
        "signals": {
            "avg_deltae_mean_7d": avg7_m,
            "avg_deltae_mean_30d": avg30_m,
            "confidence_mean_7d": conf7_m,
            "confidence_mean_30d": conf30_m,
            "decision_risk_mean_7d": risk7_m,
            "hold_rate_7d": hold7_r,
            "complaint_rate_30d": complaint30,
            "escape_rate_30d": escape30,
            "avg_deltae_trend_slope": slope,
            "run_count_7d": len(runs7),
            "run_count_30d": len(runs30),
            "outcome_count_30d": len(out30),
        },
        "driver_contributions": {k: float(v) for k, v in drivers.items()},
        "top_drivers": [{"name": k, "contribution": float(v)} for k, v in top_drivers],
        "recommendations": recommendations,
    }
