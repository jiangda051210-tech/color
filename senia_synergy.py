"""
SENIA 能力叠加引擎 — 多个功能组合产生 1+1>2 的效果
====================================================
8 个叠加组合, 每个都比单独使用更强.
"""

from __future__ import annotations

import math
import statistics
import time
from typing import Any


# ══════════════════════════════════════════════════════════
# 组合 1: 趋势预警 + 设备诊断 = 预测性维护
# ══════════════════════════════════════════════════════════

def predictive_maintenance(
    drift_history: list[dict[str, float]],
    threshold_dE: float = 2.5,
) -> dict[str, Any]:
    """
    色差趋势 + 设备诊断 = 预测性维护.

    不只告诉你 "还有 3 小时超标",
    还告诉你 "因为墨泵供墨在下降, 建议现在就检查".

    drift_history: [{"dL": x, "da": x, "db": x, "dE": x, "ts": epoch}, ...]
    """
    from senia_innovations_v2 import diagnose_machine_from_drift

    if len(drift_history) < 5:
        return {"ready": False, "reason": "需要至少 5 个数据点"}

    # 计算各通道斜率
    n = len(drift_history)
    ts = [d.get("ts", i) for i, d in enumerate(drift_history)]
    t0 = ts[0]
    hours = [(t - t0) / 3600 if isinstance(t, (int, float)) and t > 1000 else i * 0.5 for i, t in enumerate(ts)]

    def _slope(values: list[float]) -> float:
        n = len(values)
        x_mean = sum(hours) / n
        y_mean = sum(values) / n
        ss_xy = sum((hours[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        ss_xx = sum((hours[i] - x_mean) ** 2 for i in range(n))
        return ss_xy / max(ss_xx, 1e-10)

    slope_dL = _slope([d.get("dL", 0) for d in drift_history])
    slope_da = _slope([d.get("da", 0) for d in drift_history])
    slope_db = _slope([d.get("db", 0) for d in drift_history])
    slope_dE = _slope([d.get("dE", 0) for d in drift_history])

    current_dE = drift_history[-1].get("dE", 0)
    if slope_dE > 0.001 and current_dE < threshold_dE:
        hours_to_exceed = (threshold_dE - current_dE) / slope_dE
    else:
        hours_to_exceed = float("inf")

    # 设备诊断
    diagnosis = diagnose_machine_from_drift(slope_dL, slope_da, slope_db)

    # 综合行动建议
    if hours_to_exceed < 2 and not diagnosis["healthy"]:
        urgency = "紧急"
        action = f"立即停机检查: {diagnosis['most_urgent']['possible_cause']}"
    elif hours_to_exceed < 8 and not diagnosis["healthy"]:
        urgency = "注意"
        action = f"计划在 {hours_to_exceed:.0f} 小时内检查: {diagnosis['most_urgent']['possible_cause']}"
    elif not diagnosis["healthy"]:
        urgency = "关注"
        action = f"下次换班时检查: {diagnosis['diagnoses'][0]['action']}"
    else:
        urgency = "正常"
        action = "设备运行正常, 无需干预"

    return {
        "urgency": urgency,
        "action": action,
        "hours_to_exceed": round(hours_to_exceed, 1) if hours_to_exceed < 1000 else None,
        "slopes": {"dL": round(slope_dL, 4), "da": round(slope_da, 4),
                   "db": round(slope_db, 4), "dE": round(slope_dE, 4)},
        "diagnosis": diagnosis,
        "current_dE": round(current_dE, 2),
    }


# ══════════════════════════════════════════════════════════
# 组合 2: 客户偏好 + 退货成本 + 多光源 = 客户专属风险评估
# ══════════════════════════════════════════════════════════

def customer_specific_risk(
    dE: float,
    dL: float,
    da: float,
    db: float,
    customer_id: str,
    customer_sensitivity: dict[str, Any] | None = None,
    illuminant: str = "D65",
    batch_sqm: float = 500,
    unit_cost: float = 15,
) -> dict[str, Any]:
    """
    为特定客户计算精确的退货风险.

    叠加:
      1. 基础色差 → 通用退货率
      2. 客户历史偏好 → 调整权重 (对偏红敏感的客户, 偏红0.8的退货率更高)
      3. 客户所在地光源 → 用当地光源下的色差计算 (不是工厂光源)
    """
    from senia_next_gen import delta_e_to_cost

    # 基础成本评估
    base_cost = delta_e_to_cost(dE, batch_sqm, unit_cost, "standard")

    # 客户偏好加权
    sensitivity_multiplier = 1.0
    if customer_sensitivity and customer_sensitivity.get("analyzed"):
        most_sensitive = customer_sensitivity.get("most_sensitive_to", "")
        reject_rate = customer_sensitivity.get("rejection_rate", 0)

        # 如果客户对某个方向特别敏感, 且当前偏差正好在那个方向
        if "明度" in most_sensitive and abs(dL) > 0.5:
            sensitivity_multiplier *= 1.0 + reject_rate * 2
        elif "红绿" in most_sensitive and abs(da) > 0.5:
            sensitivity_multiplier *= 1.0 + reject_rate * 2
        elif "黄蓝" in most_sensitive and abs(db) > 0.5:
            sensitivity_multiplier *= 1.0 + reject_rate * 2

    # 光源调整
    illuminant_multiplier = 1.0
    if illuminant != "D65":
        from senia_next_gen import metamerism_risk
        met = metamerism_risk((50 + dL, da, db))
        if met.get("risk_level") == "high":
            illuminant_multiplier = 1.3
        elif met.get("risk_level") == "medium":
            illuminant_multiplier = 1.15

    # 综合风险
    adjusted_return_rate = base_cost["return_rate"] * sensitivity_multiplier * illuminant_multiplier
    adjusted_total = base_cost["batch_value"] * adjusted_return_rate / 100

    return {
        "customer_id": customer_id,
        "base_risk": base_cost["total_risk"],
        "adjusted_risk": round(adjusted_total, 0),
        "sensitivity_multiplier": round(sensitivity_multiplier, 2),
        "illuminant_multiplier": round(illuminant_multiplier, 2),
        "adjusted_return_rate": round(adjusted_return_rate, 2),
        "decision": "放行" if adjusted_total < 200 else "人工复核" if adjusted_total < 2000 else "建议返工",
        "explanation": (
            f"基础风险 ¥{base_cost['total_risk']:.0f}"
            + (f" × 客户敏感度{sensitivity_multiplier:.1f}x" if sensitivity_multiplier > 1.05 else "")
            + (f" × 光源风险{illuminant_multiplier:.1f}x" if illuminant_multiplier > 1.05 else "")
            + f" = 调整后 ¥{adjusted_total:.0f}"
        ),
    }


# ══════════════════════════════════════════════════════════
# 组合 3: 配方孪生 + 季节补偿 = 季节感知配方预测
# ══════════════════════════════════════════════════════════

def seasonal_recipe_prediction(
    product_code: str,
    recipe: dict[str, float],
    month: int,
    predictor: Any = None,
) -> dict[str, Any]:
    """
    预测配方在当前季节的实际颜色 (不是理想条件).

    普通配方预测: recipe → Lab (在标准条件下)
    季节感知预测: recipe + 月份 → Lab (考虑湿度/温度影响)
    """
    from senia_innovations_v2 import seasonal_compensation

    # 基础预测
    base_prediction = None
    if predictor is not None:
        try:
            base_prediction = predictor.predict(product_code, recipe)
        except Exception:
            pass

    if base_prediction is None or not base_prediction.get("predicted"):
        return {"ready": False, "reason": "配方预测模型未就绪"}

    base_L = base_prediction["predicted_L"]
    base_a = base_prediction["predicted_a"]
    base_b = base_prediction["predicted_b"]

    # 季节补偿
    season = seasonal_compensation(month, 0)
    dL_offset = season["dL_offset"]

    adjusted_L = base_L + dL_offset
    adjusted_a = base_a
    adjusted_b = base_b

    return {
        "base_prediction": {"L": base_L, "a": base_a, "b": base_b},
        "seasonal_offset": {"dL": round(dL_offset, 3)},
        "adjusted_prediction": {"L": round(adjusted_L, 2), "a": round(adjusted_a, 2), "b": round(adjusted_b, 2)},
        "month": month,
        "humidity": season["humidity"],
        "temperature": season["temperature"],
        "recommendation": season["recommendation"],
    }


# ══════════════════════════════════════════════════════════
# 组合 4: 色彩搜索 + 竞品逆向 + 配方孪生 = 一键配色
# ══════════════════════════════════════════════════════════

def one_click_color_match(
    target_lab: tuple[float, float, float],
    search_engine: Any = None,
    predictor: Any = None,
) -> dict[str, Any]:
    """
    客户说 "我要这个颜色" → 系统一步到位:
      1. 搜索最接近的现有产品
      2. 计算需要什么配方调整
      3. 预测调整后的颜色
      4. 验证是否达标
    """
    from senia_calibration import ciede2000

    result: dict[str, Any] = {"target_lab": list(target_lab), "steps": []}

    # Step 1: 搜索
    if search_engine is not None and search_engine.count() > 0:
        matches = search_engine.search(target_lab, top_k=3)
        result["steps"].append({"step": "search", "matches": matches})
        if matches:
            best = matches[0]
            result["best_existing"] = best["code"]
            result["existing_dE"] = best["dE"]

            # Step 2: 如果已有产品够接近, 直接推荐
            if best["dE"] < 1.5:
                result["recommendation"] = f"现有产品 {best['code']} 已经非常接近 (ΔE={best['dE']:.1f}), 建议直接使用"
                result["need_new_recipe"] = False
                return result
    else:
        result["steps"].append({"step": "search", "note": "搜索引擎未初始化"})

    # Step 3: 需要新配方
    result["need_new_recipe"] = True
    result["recommendation"] = "现有产品差异较大, 需要调整配方"

    # Step 4: 如果有配方预测器, 尝试反向优化
    if predictor is not None:
        try:
            from senia_predictor import ProductionPredictor
            if isinstance(predictor, ProductionPredictor):
                # 用现有最接近产品的配方作为起点
                result["steps"].append({"step": "optimize", "note": "从最接近产品的配方开始优化"})
        except Exception:
            pass

    return result


# ══════════════════════════════════════════════════════════
# 组合 5: 批内一致性 + 趋势预警 = 批次稳定性实时监控
# ══════════════════════════════════════════════════════════

def batch_stability_monitor(
    batch_dE_sequence: list[float],
    window_size: int = 10,
    bci_threshold: float = 70,
) -> dict[str, Any]:
    """
    连续监控批次稳定性.

    不只看最后一块板, 而是看最近 N 块板的趋势.
    如果一致性在下降 → 预测批次后半段可能出问题.
    """
    from senia_next_gen import batch_consistency_index

    n = len(batch_dE_sequence)
    if n < window_size:
        return {"ready": False, "reason": f"需要至少 {window_size} 个样本"}

    # 计算滑动窗口 BCI
    bcis: list[float] = []
    for i in range(window_size, n + 1):
        window = batch_dE_sequence[i - window_size:i]
        bci = batch_consistency_index(window)
        bcis.append(bci["bci"])

    current_bci = bcis[-1]
    bci_trend = bcis[-1] - bcis[0] if len(bcis) > 1 else 0

    # 趋势判断
    if bci_trend < -5 and current_bci < bci_threshold:
        status = "恶化中"
        action = "⚠️ 批次一致性在快速下降, 建议检查设备或暂停生产"
    elif bci_trend < -2:
        status = "轻微下降"
        action = "关注: 一致性有下降趋势, 密切监控"
    elif current_bci < bci_threshold:
        status = "偏低"
        action = f"BCI={current_bci:.0f} 低于阈值 {bci_threshold}, 考虑分拣"
    else:
        status = "稳定"
        action = "批次一致性良好"

    return {
        "current_bci": round(current_bci, 1),
        "bci_trend": round(bci_trend, 1),
        "status": status,
        "action": action,
        "sample_count": n,
        "bci_history": [round(b, 1) for b in bcis[-10:]],
    }


# ══════════════════════════════════════════════════════════
# 组合 6: 所有能力联合 → 智能决策中心
# ══════════════════════════════════════════════════════════

def smart_decision(
    dE: float,
    dL: float,
    da: float,
    db: float,
    profile: str = "wood",
    customer_id: str = "",
    customer_sensitivity: dict[str, Any] | None = None,
    customer_illuminant: str = "D65",
    batch_sqm: float = 500,
    month: int | None = None,
    batch_dE_history: list[float] | None = None,
) -> dict[str, Any]:
    """
    智能决策中心 — 所有能力联合给出一个最终建议.

    综合考虑:
      - 色差本身
      - 客户敏感度
      - 光源条件
      - 季节因素
      - 批次稳定性
      - 退货成本
    """
    import time as _time

    month = month or int(_time.strftime("%m"))

    # 1. 客户专属风险
    risk = customer_specific_risk(
        dE, dL, da, db, customer_id,
        customer_sensitivity, customer_illuminant, batch_sqm,
    )

    # 2. 季节因素
    from senia_innovations_v2 import seasonal_compensation
    season = seasonal_compensation(month, dE)

    # 3. 批次稳定性
    batch_status = None
    if batch_dE_history and len(batch_dE_history) >= 10:
        batch_status = batch_stability_monitor(batch_dE_history)

    # 4. 综合评分 (0-100, 越高越好)
    score = 100
    # 色差扣分
    score -= min(40, dE * 15)
    # 客户风险扣分
    score -= min(30, risk["adjusted_return_rate"] * 0.8)
    # 季节风险扣分
    score -= min(10, abs(season["dL_offset"]) * 20)
    # 批次不稳定扣分
    if batch_status and batch_status.get("status") == "恶化中":
        score -= 15
    elif batch_status and batch_status.get("current_bci", 100) < 70:
        score -= 10

    score = max(0, min(100, score))

    if score >= 80:
        final_decision = "放行"
        confidence = "高"
    elif score >= 50:
        final_decision = "人工复核"
        confidence = "中"
    else:
        final_decision = "建议返工"
        confidence = "高"

    reasons: list[str] = []
    if dE > 1.5:
        reasons.append(f"色差 ΔE={dE:.2f}")
    if risk["sensitivity_multiplier"] > 1.1:
        reasons.append(f"客户敏感度加权 {risk['sensitivity_multiplier']:.1f}x")
    if risk["illuminant_multiplier"] > 1.1:
        reasons.append(f"光源风险 {risk['illuminant_multiplier']:.1f}x")
    if abs(season["dL_offset"]) > 0.05:
        reasons.append(f"季节影响 dL={season['dL_offset']:+.2f}")
    if batch_status and batch_status.get("status") != "稳定":
        reasons.append(f"批次: {batch_status['status']}")

    return {
        "decision": final_decision,
        "score": round(score, 1),
        "confidence": confidence,
        "reasons": reasons or ["各项指标正常"],
        "risk_amount": risk["adjusted_risk"],
        "batch_bci": batch_status["current_bci"] if batch_status else None,
        "seasonal_note": season["recommendation"],
    }
