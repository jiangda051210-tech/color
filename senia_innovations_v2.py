"""
SENIA 行业独创功能集
====================
8 个全新能力, 市场上完全不存在.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any
import json


# ══════════════════════════════════════════════════════════
# 1. 色差趋势预警 — 提前 N 小时预警色差要超标
# ══════════════════════════════════════════════════════════

class DriftEarlyWarning:
    """
    不是等出问题才发现, 而是提前预警.

    原理: 跟踪最近 N 次测量的 ΔE 趋势线.
    如果斜率 > 0 且按当前速率 M 小时后会超过阈值 → 预警.

    应用: 印刷过程中色差在缓慢漂移, 操作员看不出来,
    但系统发现每小时 ΔE 上升 0.1, 再过 3 小时就会超标.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        # line_id → [(timestamp, dE)]
        self._history: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def record(self, line_id: str, dE: float) -> None:
        with self._lock:
            self._history[line_id].append((time.time(), dE))
            # 保留最近 200 条
            if len(self._history[line_id]) > 200:
                self._history[line_id] = self._history[line_id][-200:]

    def predict(self, line_id: str, threshold_dE: float = 2.5,
                hours_ahead: float = 8.0) -> dict[str, Any]:
        with self._lock:
            data = self._history.get(line_id, [])

        if len(data) < 5:
            return {"warning": False, "reason": "数据不足 (需要≥5次测量)"}

        # 线性回归: dE = a*t + b
        ts = [d[0] for d in data]
        des = [d[1] for d in data]
        t0 = ts[0]
        xs = [(t - t0) / 3600 for t in ts]  # 转为小时
        n = len(xs)
        x_mean = sum(xs) / n
        y_mean = sum(des) / n
        ss_xy = sum((xs[i] - x_mean) * (des[i] - y_mean) for i in range(n))
        ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
        if ss_xx < 1e-10:
            return {"warning": False, "reason": "时间跨度不足"}

        slope = ss_xy / ss_xx  # ΔE 每小时变化量
        intercept = y_mean - slope * x_mean
        current_hours = (ts[-1] - t0) / 3600

        # 预测
        predicted_now = slope * current_hours + intercept
        predicted_future = slope * (current_hours + hours_ahead) + intercept

        # 几小时后超标?
        if slope > 0.01 and predicted_now < threshold_dE:
            hours_to_exceed = (threshold_dE - intercept) / slope - current_hours
            hours_to_exceed = max(0, hours_to_exceed)
        else:
            hours_to_exceed = float("inf")

        warning = hours_to_exceed < hours_ahead and slope > 0.01

        return {
            "warning": warning,
            "slope_per_hour": round(slope, 4),
            "current_dE": round(des[-1], 2),
            "predicted_dE_now": round(predicted_now, 2),
            "predicted_dE_future": round(predicted_future, 2),
            "hours_to_exceed": round(hours_to_exceed, 1) if hours_to_exceed < 1000 else None,
            "threshold": threshold_dE,
            "data_points": n,
            "message": f"⚠️ 预计 {hours_to_exceed:.1f} 小时后色差超标 (当前趋势: 每小时+{slope:.3f} ΔE)" if warning
                       else "色差趋势稳定" if slope <= 0.01
                       else f"色差在缓慢上升 (每小时+{slope:.3f}), 但短期内不会超标",
        }


# ══════════════════════════════════════════════════════════
# 2. 竞品色彩逆向 — 从颜色反推配方
# ══════════════════════════════════════════════════════════

def reverse_engineer_color(
    target_lab: tuple[float, float, float],
    known_recipes: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    客户拿竞品样品来说"我要这个颜色", 系统从已有配方库找最接近的,
    并计算调整方向.

    known_recipes: [{"name": "AW-001", "lab": (55, -1, 8), "recipe": {"C":40,...}}, ...]
    """
    from senia_calibration import ciede2000

    if not known_recipes:
        return {"found": False, "reason": "配方库为空"}

    L, a, b = target_lab
    scored = []
    for kr in known_recipes:
        kr_lab = kr.get("lab", (50, 0, 0))
        de = ciede2000(L, a, b, kr_lab[0], kr_lab[1], kr_lab[2])
        scored.append({
            "name": kr.get("name", ""),
            "dE": de["dE00"],
            "dL": de["dL"],
            "dC": de["dC"],
            "recipe": kr.get("recipe", {}),
            "lab": list(kr_lab),
        })
    scored.sort(key=lambda x: x["dE"])

    best = scored[0]
    adjustments: list[str] = []
    if abs(best["dL"]) > 0.5:
        adjustments.append("偏亮→减白" if best["dL"] > 0 else "偏暗→加白")
    if abs(best["dC"]) > 0.5:
        adjustments.append("饱和度调整" if best["dC"] > 0 else "加浓色精")

    return {
        "found": True,
        "best_match": best["name"],
        "dE_to_target": round(best["dE"], 2),
        "base_recipe": best["recipe"],
        "adjustments": adjustments or ["配方基本吻合, 微调即可"],
        "top_3": scored[:3],
    }


# ══════════════════════════════════════════════════════════
# 3. 色彩搜索引擎 — "找和这个颜色最接近的现有产品"
# ══════════════════════════════════════════════════════════

class ColorSearchEngine:
    """
    像搜索引擎一样搜索颜色.
    输入一个 Lab 值, 返回最接近的 N 个产品.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._products: list[dict[str, Any]] = []

    def index(self, product_code: str, lab: tuple[float, float, float],
              name: str = "", category: str = "") -> None:
        with self._lock:
            self._products.append({
                "code": product_code, "lab": list(lab),
                "name": name, "category": category,
            })

    def search(self, query_lab: tuple[float, float, float],
               top_k: int = 5, category: str = "") -> list[dict[str, Any]]:
        from senia_calibration import ciede2000
        L, a, b = query_lab
        results = []
        with self._lock:
            for p in self._products:
                if category and p.get("category") != category:
                    continue
                plab = p["lab"]
                de = ciede2000(L, a, b, plab[0], plab[1], plab[2])
                results.append({**p, "dE": de["dE00"],
                                "match_quality": "完美" if de["dE00"] < 1 else "接近" if de["dE00"] < 3 else "偏远"})
        results.sort(key=lambda x: x["dE"])
        return results[:top_k]

    def count(self) -> int:
        return len(self._products)


# ══════════════════════════════════════════════════════════
# 4. 客户色彩偏好学习
# ══════════════════════════════════════════════════════════

class CustomerColorProfile:
    """
    学习每个客户的色彩敏感度.

    有的客户对偏红很敏感 (退过红色偏差的货),
    有的客户对明度很敏感 (退过偏暗的货).
    系统学习后, 对不同客户用不同的阈值权重.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        # customer_id → [{"dL": x, "da": x, "db": x, "accepted": bool}]
        self._records: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def record_decision(self, customer_id: str, dL: float, da: float, db: float,
                        accepted: bool) -> None:
        with self._lock:
            self._records[customer_id].append({
                "dL": dL, "da": da, "db": db, "accepted": accepted,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

    def get_sensitivity(self, customer_id: str) -> dict[str, Any]:
        """分析客户对哪个色差方向最敏感."""
        with self._lock:
            records = self._records.get(customer_id, [])
        if len(records) < 5:
            return {"analyzed": False, "reason": "数据不足 (需要≥5条记录)"}

        rejected = [r for r in records if not r["accepted"]]
        if not rejected:
            return {"analyzed": True, "sensitivity": "low", "note": "该客户从未退货"}

        # 统计退货时的偏差方向
        reject_dL = [abs(r["dL"]) for r in rejected]
        reject_da = [abs(r["da"]) for r in rejected]
        reject_db = [abs(r["db"]) for r in rejected]

        avg_dL = statistics.mean(reject_dL) if reject_dL else 0
        avg_da = statistics.mean(reject_da) if reject_da else 0
        avg_db = statistics.mean(reject_db) if reject_db else 0

        # 哪个维度的退货偏差最小 = 该客户对这个维度最敏感
        sensitivities = {"明度(dL)": avg_dL, "红绿(da)": avg_da, "黄蓝(db)": avg_db}
        most_sensitive = min(sensitivities, key=sensitivities.get)

        return {
            "analyzed": True,
            "total_records": len(records),
            "rejection_rate": round(len(rejected) / len(records), 3),
            "most_sensitive_to": most_sensitive,
            "avg_rejected_dL": round(avg_dL, 2),
            "avg_rejected_da": round(avg_da, 2),
            "avg_rejected_db": round(avg_db, 2),
            "recommendation": f"该客户对{most_sensitive}最敏感, 建议收紧该方向阈值",
        }


# ══════════════════════════════════════════════════════════
# 5. 印刷机状态推断 — 从色差趋势诊断设备
# ══════════════════════════════════════════════════════════

def diagnose_machine_from_drift(
    drift_slope_dL: float,
    drift_slope_da: float,
    drift_slope_db: float,
    sensitivity_config: dict | None = None,
) -> dict[str, Any]:
    """
    从色差漂移方向推断印刷机可能的故障.

    ΔL 持续上升 → 墨量减少 → 可能墨泵供墨不足或刮刀磨损
    Δa 持续偏移 → 某路色精供墨不均
    Δb 持续上升 → 黄色组分增多 → 可能墨路混色或清洗不彻底

    sensitivity_config: optional dict to override default thresholds, e.g.
        {"dL_threshold": 0.02, "da_threshold": 0.015, "db_threshold": 0.015,
         "db_high_urgency_threshold": 0.03}
    """
    cfg = sensitivity_config or {}
    dL_threshold = cfg.get("dL_threshold", 0.02)
    da_threshold = cfg.get("da_threshold", 0.015)
    db_threshold = cfg.get("db_threshold", 0.015)
    db_high_urgency_threshold = cfg.get("db_high_urgency_threshold", 0.03)

    diagnoses: list[dict[str, str]] = []

    if drift_slope_dL > dL_threshold:
        diagnoses.append({
            "symptom": f"明度持续上升 (+{drift_slope_dL:.3f}/h)",
            "possible_cause": "墨泵供墨不足 或 刮刀磨损",
            "urgency": "medium",
            "action": "检查墨泵压力和刮刀状态",
        })
    elif drift_slope_dL < -dL_threshold:
        diagnoses.append({
            "symptom": f"明度持续下降 ({drift_slope_dL:.3f}/h)",
            "possible_cause": "墨量过多 或 涂布厚度增加",
            "urgency": "low",
            "action": "检查涂布辊间距",
        })

    if abs(drift_slope_da) > da_threshold:
        direction = "偏红" if drift_slope_da > 0 else "偏绿"
        diagnoses.append({
            "symptom": f"红绿轴漂移 ({direction}, {drift_slope_da:+.3f}/h)",
            "possible_cause": f"{'红色' if drift_slope_da > 0 else '绿色'}色精供墨不均",
            "urgency": "medium",
            "action": "检查对应色精墨路和搅拌器",
        })

    if abs(drift_slope_db) > db_threshold:
        direction = "偏黄" if drift_slope_db > 0 else "偏蓝"
        diagnoses.append({
            "symptom": f"黄蓝轴漂移 ({direction}, {drift_slope_db:+.3f}/h)",
            "possible_cause": "墨路混色" if drift_slope_db > 0 else "蓝色色精过量",
            "urgency": "high" if abs(drift_slope_db) > db_high_urgency_threshold else "medium",
            "action": "检查墨路清洗状况和色精比例",
        })

    if not diagnoses:
        return {"healthy": True, "message": "设备运行正常, 色差稳定"}

    return {
        "healthy": False,
        "diagnoses": diagnoses,
        "most_urgent": max(diagnoses, key=lambda d: {"low": 0, "medium": 1, "high": 2}[d["urgency"]]),
        "message": f"检测到 {len(diagnoses)} 个异常信号",
    }


# ══════════════════════════════════════════════════════════
# 6. 季节性色差补偿
# ══════════════════════════════════════════════════════════

def seasonal_compensation(
    month: int,
    base_dE: float,
    humidity: float | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """
    同样配方在不同季节出来的颜色不一样.
    夏天湿度高 → 干燥慢 → 颜色偏深
    冬天干燥 → 干燥快 → 颜色偏浅

    如果没有传入实际湿度/温度, 用季节性默认值.
    """
    # 中国东部沿海城市典型气候 (适用于大多数地板出口工厂)
    seasonal_defaults = {
        1: (45, 5), 2: (50, 8), 3: (60, 14), 4: (65, 20),
        5: (72, 25), 6: (80, 28), 7: (85, 32), 8: (82, 31),
        9: (72, 26), 10: (60, 20), 11: (50, 13), 12: (45, 7),
    }

    if humidity is None or temperature is None:
        h_default, t_default = seasonal_defaults.get(month, (60, 20))
        humidity = humidity or h_default
        temperature = temperature or t_default

    # 湿度影响: 高湿度 → 颜色偏深 (ΔL 负向)
    humidity_offset_dL = -(humidity - 60) * 0.008  # 每 10% 湿度 ≈ 0.08 ΔL

    # 温度影响: 高温 → 墨水粘度低 → 涂布薄 → 颜色偏浅
    temp_offset_dL = (temperature - 20) * 0.005

    # 综合影响
    total_offset = humidity_offset_dL + temp_offset_dL
    adjusted_dE = max(0, base_dE + abs(total_offset) * 0.3)

    return {
        "month": month,
        "humidity": humidity,
        "temperature": temperature,
        "dL_offset": round(total_offset, 3),
        "adjusted_dE": round(adjusted_dE, 3),
        "original_dE": base_dE,
        "recommendation": (
            f"当前季节(湿度{humidity}%/温度{temperature}°C)建议配方微调: "
            + ("减少涂布量或加快干燥速度" if total_offset < -0.05
               else "适当增加涂布量" if total_offset > 0.05
               else "无需季节性调整")
        ),
    }


# ══════════════════════════════════════════════════════════
# 7. 多角度色差 (各向异性)
# ══════════════════════════════════════════════════════════

def anisotropy_analysis(
    dE_0deg: float,
    dE_45deg: float | None = None,
    dE_90deg: float | None = None,
) -> dict[str, Any]:
    """
    地板有纹理方向, 不同角度看到的颜色不同.
    顺纹看和横纹看, 色差可能差 0.5-1.5 ΔE.

    如果只有 0° 数据, 用经验模型估算其他角度.
    """
    if dE_45deg is None:
        # 经验模型: 木纹膜的 45° 色差通常比 0° 大 15-25%
        dE_45deg = dE_0deg * 1.2
    if dE_90deg is None:
        dE_90deg = dE_0deg * 1.35

    max_dE = max(dE_0deg, dE_45deg, dE_90deg)
    anisotropy_index = (max_dE - min(dE_0deg, dE_45deg, dE_90deg)) / max(max_dE, 0.01)

    return {
        "dE_0deg": round(dE_0deg, 3),
        "dE_45deg": round(dE_45deg, 3),
        "dE_90deg": round(dE_90deg, 3),
        "worst_angle": "90° (横纹)" if dE_90deg >= dE_45deg else "45°",
        "worst_dE": round(max_dE, 3),
        "anisotropy_index": round(anisotropy_index, 3),
        "note": (
            "各向异性较大, 建议检查时同时看顺纹和横纹方向" if anisotropy_index > 0.3
            else "各向异性在正常范围" if anisotropy_index > 0.1
            else "接近各向同性, 无纹理方向影响"
        ),
    }


# ══════════════════════════════════════════════════════════
# 8. AR 色彩预览数据 (给前端 AR 模块用)
# ══════════════════════════════════════════════════════════

def generate_ar_preview_data(
    product_lab: tuple[float, float, float],
    room_illuminant: str = "A",
) -> dict[str, Any]:
    """
    生成 AR 预览所需的色彩数据.
    前端用 WebGL/Three.js 渲染地板铺设效果.

    输出: 目标 sRGB 颜色 (在指定光源下),
          纹理参数, 光泽度参数.
    """
    from senia_advanced_color import predict_under_illuminant
    import numpy as np

    lab = np.array([[product_lab]], dtype=np.float32)
    adapted_lab = predict_under_illuminant(lab, room_illuminant).ravel()

    # Lab → sRGB (近似)
    L, a, b = adapted_lab
    # 简化转换
    fy = (L + 16) / 116
    fx = a / 500 + fy
    fz = fy - b / 200

    def inv_f(t):
        return t ** 3 if t > 6 / 29 else (t - 16 / 116) / 7.787

    X = inv_f(fx) * 0.9642
    Y = inv_f(fy)
    Z = inv_f(fz) * 0.8249

    # XYZ → linear sRGB
    r = 3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
    g = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
    bl = 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z

    def gamma(c):
        c = max(0, min(1, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    srgb = (int(gamma(r) * 255 + 0.5), int(gamma(g) * 255 + 0.5), int(gamma(bl) * 255 + 0.5))
    hex_color = f"#{srgb[0]:02x}{srgb[1]:02x}{srgb[2]:02x}"

    illum_names = {"A": "暖色灯", "F11": "商场灯", "D65": "日光", "LED": "LED灯"}
    return {
        "illuminant": room_illuminant,
        "lab_adapted": [round(float(adapted_lab[0]), 2), round(float(adapted_lab[1]), 2), round(float(adapted_lab[2]), 2)],
        "srgb": list(srgb),
        "hex": hex_color,
        "preview_note": f"在{illum_names.get(room_illuminant, room_illuminant)}下的预览颜色",
    }
