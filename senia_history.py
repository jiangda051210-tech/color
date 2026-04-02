"""
SENIA 批次历史对比 + 漂移检测
============================
跟踪同一批次/产品的多次分析结果, 发现趋势和异常.
"""

from __future__ import annotations

import sqlite3
import statistics
import time
from pathlib import Path
from typing import Any


def query_lot_history(
    db_path: Path,
    lot_id: str = "",
    product_code: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询某批次/产品的历史分析记录."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conditions = []
        params: list[Any] = []
        if lot_id:
            conditions.append("lot_id = ?")
            params.append(lot_id)
        if product_code:
            conditions.append("product_code = ?")
            params.append(product_code)
        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(min(limit, 500))
        rows = conn.execute(
            f"SELECT * FROM quality_runs WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def compute_lot_trend(
    db_path: Path,
    lot_id: str = "",
    product_code: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    """
    计算批次/产品的色差趋势.

    返回:
      - trend_direction: "improving" / "stable" / "degrading"
      - avg_dE: 历史平均色差
      - latest_dE: 最近一次色差
      - pass_rate: 合格率
      - drift_detected: 是否检测到漂移
    """
    history = query_lot_history(db_path, lot_id, product_code, limit)
    if not history:
        return {
            "has_history": False,
            "reason": "no previous records for this lot/product",
        }

    de_values: list[float] = []
    pass_count = 0
    for row in history:
        try:
            report_json = row.get("report_json", "")
            if isinstance(report_json, str) and report_json:
                import json
                report = json.loads(report_json)
                de = report.get("result", {}).get("summary", {}).get("avg_delta_e00")
                if de is not None:
                    de_values.append(float(de))
                tier = report.get("tier", "")
                if tier == "PASS":
                    pass_count += 1
            else:
                avg_de = row.get("avg_de")
                if avg_de is not None:
                    de_values.append(float(avg_de))
                decision = row.get("decision", "")
                if decision == "PASS" or decision == "AUTO_RELEASE":
                    pass_count += 1
        except (TypeError, ValueError, KeyError):
            continue

    if not de_values:
        return {"has_history": True, "record_count": len(history), "reason": "no valid dE in records"}

    n = len(de_values)
    avg_dE = statistics.mean(de_values)
    latest_dE = de_values[0] if de_values else 0
    pass_rate = pass_count / max(len(history), 1)

    # 趋势检测: 对比前半 vs 后半
    if n >= 4:
        first_half = statistics.mean(de_values[n // 2:])  # 较早的
        second_half = statistics.mean(de_values[:n // 2])  # 较近的
        delta = second_half - first_half
        if delta > 0.3:
            trend = "degrading"
        elif delta < -0.3:
            trend = "improving"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    # 漂移检测: 最新值是否偏离历史均值 > 2σ
    drift_detected = False
    drift_magnitude = 0.0
    if n >= 5:
        std_dE = statistics.stdev(de_values[1:]) if n > 2 else 1.0
        if std_dE > 0.01:
            z_score = abs(latest_dE - avg_dE) / std_dE
            drift_detected = z_score > 2.0
            drift_magnitude = round(z_score, 2)

    return {
        "has_history": True,
        "record_count": n,
        "avg_dE": round(avg_dE, 4),
        "latest_dE": round(latest_dE, 4),
        "min_dE": round(min(de_values), 4),
        "max_dE": round(max(de_values), 4),
        "pass_rate": round(pass_rate, 4),
        "trend_direction": trend,
        "drift_detected": drift_detected,
        "drift_magnitude": drift_magnitude,
        "history_dE_values": [round(v, 4) for v in de_values[:20]],
    }


def compare_with_baseline(
    current_dE: float,
    db_path: Path,
    lot_id: str = "",
    product_code: str = "",
) -> dict[str, Any]:
    """
    将当前结果与历史基线对比.

    返回:
      - vs_baseline: "better" / "same" / "worse"
      - baseline_avg: 历史平均
      - percentile: 当前值在历史中的百分位
    """
    trend = compute_lot_trend(db_path, lot_id, product_code)
    if not trend.get("has_history") or trend.get("record_count", 0) < 2:
        return {"has_baseline": False, "reason": "insufficient history"}

    avg = trend["avg_dE"]
    values = trend.get("history_dE_values", [])

    # 当前值在历史中的百分位
    if values:
        below = sum(1 for v in values if v <= current_dE)
        percentile = below / len(values)
    else:
        percentile = 0.5

    if current_dE < avg * 0.8:
        vs = "better"
    elif current_dE > avg * 1.2:
        vs = "worse"
    else:
        vs = "same"

    return {
        "has_baseline": True,
        "vs_baseline": vs,
        "baseline_avg": avg,
        "current_dE": round(current_dE, 4),
        "percentile": round(percentile, 4),
        "trend": trend["trend_direction"],
        "drift_detected": trend["drift_detected"],
    }
