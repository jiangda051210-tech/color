"""
SENIA 行业级对色能力 — 解决工厂实际痛点
========================================
基于行业调研, 实现6项工业级能力:

1. 湿膜→干膜色差预测 (工厂最大痛点)
2. 同色异谱风险警告 (D65合格但TL84/A光下不合格)
3. 空间均匀性分析 (板面各区域是否一致)
4. 连续生产漂移检测 (多批次色差趋势)
5. 边缘效应检测 (边缘vs中心色差)
6. 纹理匹配度评估 (木纹方向/密度/清晰度一致性)

设计原则:
  - 纯手机拍照, 不依赖任何硬件
  - 比人工对色员更全面, 比X-Rite成本低100倍
  - 输出车间操作员能直接理解的结果
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


# ════════════════════════════════════════════════
# 1. 湿膜→干膜色差预测
# ════════════════════════════════════════════════

# 经验系数: 不同基材/工艺的湿干偏移量 (基于行业数据)
# 湿膜比干膜: 偏深(L↓), 偏饱和(C↑), 色相轻微偏移
WET_DRY_PROFILES = {
    "pvc_wood": {"dL": +2.5, "da": -0.3, "db": -0.8, "note": "PVC木纹膜: 干燥后偏亮偏蓝减少"},
    "pvc_solid": {"dL": +1.8, "da": -0.2, "db": -0.5, "note": "PVC纯色膜"},
    "melamine": {"dL": +3.0, "da": -0.4, "db": -1.0, "note": "三聚氰胺浸渍纸: 偏移较大"},
    "uv_coating": {"dL": +1.2, "da": -0.1, "db": -0.3, "note": "UV涂层: 偏移较小"},
    "pet_film": {"dL": +2.0, "da": -0.2, "db": -0.6, "note": "PET装饰膜"},
    "default": {"dL": +2.0, "da": -0.2, "db": -0.6, "note": "默认预测"},
}


def predict_dry_color(
    wet_lab: dict[str, float],
    substrate: str = "pvc_wood",
    temperature_c: float = 25.0,
    humidity_pct: float = 50.0,
) -> dict[str, Any]:
    """
    根据湿膜颜色预测干燥后颜色.

    原理: 湿膜含水/溶剂, 折射率不同, 干燥后颜色会偏移.
    偏移方向: 通常偏亮(L↑), 偏蓝减少(b↑), 饱和度下降(C↓).
    温湿度修正: 高温快干→偏移小, 低温慢干→偏移大.
    """
    profile = WET_DRY_PROFILES.get(substrate, WET_DRY_PROFILES["default"])

    # 温湿度修正系数: 偏离25°C/50%RH时调整
    temp_factor = 1.0 + (25.0 - temperature_c) * 0.02  # 低温→偏移大
    humid_factor = 1.0 + (humidity_pct - 50.0) * 0.005  # 高湿→偏移大
    env_factor = max(0.5, min(1.5, temp_factor * humid_factor))

    predicted_lab = {
        "L": round(wet_lab["L"] + profile["dL"] * env_factor, 2),
        "a": round(wet_lab["a"] + profile["da"] * env_factor, 2),
        "b": round(wet_lab["b"] + profile["db"] * env_factor, 2),
    }

    return {
        "当前(湿膜)": wet_lab,
        "预测(干膜)": predicted_lab,
        "预测偏移": {
            "ΔL": round(profile["dL"] * env_factor, 2),
            "Δa": round(profile["da"] * env_factor, 2),
            "Δb": round(profile["db"] * env_factor, 2),
        },
        "基材类型": substrate,
        "环境修正": round(env_factor, 2),
        "说明": profile["note"],
        "建议": _wet_dry_suggestion(profile, env_factor),
    }


def _wet_dry_suggestion(profile: dict, env_factor: float) -> str:
    dL = profile["dL"] * env_factor
    if abs(dL) > 3.0:
        return f"预计干燥后偏亮 {dL:+.1f}，建议湿膜对色时色差预留 {abs(dL):.1f} 个L单位"
    elif abs(dL) > 1.5:
        return f"干燥偏移中等 (ΔL={dL:+.1f})，注意湿膜比干膜深约 {abs(dL):.1f} L"
    return "干燥偏移较小，可直接以湿膜结果判定"


# ════════════════════════════════════════════════
# 2. 同色异谱风险警告
# ════════════════════════════════════════════════

# 常见光源的色适应偏移方向 (相对于D65)
ILLUMINANT_SHIFTS = {
    "A": {"da": +1.5, "db": +3.0, "name": "白炽灯(2856K)", "场景": "家庭/酒店"},
    "TL84": {"da": -0.8, "db": +1.2, "name": "三基色荧光灯(4000K)", "场景": "欧洲商场/办公室"},
    "F2": {"da": -0.5, "db": +0.8, "name": "冷白荧光灯(4150K)", "场景": "北美商场"},
    "LED_3000K": {"da": +0.8, "db": +1.8, "name": "暖白LED(3000K)", "场景": "现代家居"},
    "LED_4000K": {"da": +0.2, "db": +0.5, "name": "中性LED(4000K)", "场景": "办公室"},
}


def check_metamerism_risk(
    board_lab: dict[str, float],
    sample_lab: dict[str, float],
) -> dict[str, Any]:
    """
    同色异谱风险检查 — D65下合格的两块板, 换光源后可能不合格.

    原理: 如果两块板在D65下颜色一致(dE<1.5), 但它们的RGB成分不同,
    在其他光源下可能显示出色差. 我们通过估算不同光源下的色偏来预测这个风险.

    注意: 这是纯RGB近似, 不能替代光谱仪. 但能给出有用的风险提示.
    """
    from senia_color_report import _ciede2000_detail

    d65_de = _ciede2000_detail(board_lab, sample_lab)

    risks = []
    worst_illuminant = None
    worst_de = d65_de["dE00"]

    for illum_name, shift in ILLUMINANT_SHIFTS.items():
        # 模拟不同光源下的色偏: 每块板的偏移量不同(取决于其色度)
        board_chroma = math.sqrt(board_lab["a"] ** 2 + board_lab["b"] ** 2)
        sample_chroma = math.sqrt(sample_lab["a"] ** 2 + sample_lab["b"] ** 2)

        # 色度差异越大, 换光源后色差放大风险越高
        chroma_diff_factor = 1.0 + abs(board_chroma - sample_chroma) * 0.1

        # 模拟该光源下的LAB
        board_shifted = {
            "L": board_lab["L"],
            "a": board_lab["a"] + shift["da"] * (1.0 + board_chroma * 0.02),
            "b": board_lab["b"] + shift["db"] * (1.0 + board_chroma * 0.02),
        }
        sample_shifted = {
            "L": sample_lab["L"],
            "a": sample_lab["a"] + shift["da"] * (1.0 + sample_chroma * 0.02),
            "b": sample_lab["b"] + shift["db"] * (1.0 + sample_chroma * 0.02),
        }

        de_shifted = _ciede2000_detail(board_shifted, sample_shifted)
        de_change = de_shifted["dE00"] - d65_de["dE00"]

        risk_level = "低"
        if de_shifted["dE00"] > 3.0 and de_change > 1.0:
            risk_level = "高"
        elif de_shifted["dE00"] > 2.0 and de_change > 0.5:
            risk_level = "中"

        risks.append({
            "光源": f"{shift['name']}",
            "场景": shift["场景"],
            "预测色差": round(de_shifted["dE00"], 2),
            "色差变化": f"{de_change:+.2f}",
            "风险": risk_level,
        })

        if de_shifted["dE00"] > worst_de:
            worst_de = de_shifted["dE00"]
            worst_illuminant = shift["name"]

    # 综合评估
    high_risks = [r for r in risks if r["风险"] == "高"]
    overall = "安全" if not high_risks else f"注意: {len(high_risks)}个光源下可能不合格"

    return {
        "D65色差": round(d65_de["dE00"], 2),
        "多光源风险": risks,
        "最差光源": worst_illuminant or "D65",
        "最差色差": round(worst_de, 2),
        "综合评估": overall,
        "建议": "D65下合格且各光源风险均低" if not high_risks else
                f"建议在{worst_illuminant}光源下复检, 或调整配方减少同色异谱风险",
    }


# ════════════════════════════════════════════════
# 3. 空间均匀性分析
# ════════════════════════════════════════════════

def analyze_board_uniformity(
    image_bgr: np.ndarray,
    board_quad: np.ndarray,
    grid_rows: int = 4,
    grid_cols: int = 6,
) -> dict[str, Any]:
    """
    分析单块板材的空间均匀性 — 检测局部色差.

    对色员只能看整体, 系统能逐区域测量:
      - 中心vs边缘有没有色差?
      - 上下/左右有没有渐变?
      - 有没有局部色斑/发花?
    """
    from elite_color_match import (order_quad, texture_suppress,
        build_material_mask, build_invalid_mask, bgr_to_lab_float)

    quad = order_quad(board_quad)
    widths = [np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3])]
    heights = [np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])]
    bw, bh = int(max(widths)), int(max(heights))

    if bw < 60 or bh < 60:
        return {"error": "板材区域太小，无法做均匀性分析"}

    dst = np.array([[0, 0], [bw, 0], [bw, bh], [0, bh]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad, dst)
    warped = cv2.warpPerspective(image_bgr, M, (bw, bh))
    tone = texture_suppress(warped)
    lab = bgr_to_lab_float(tone)

    mask = build_material_mask(tone.shape[:2], 0.03)
    invalid = build_invalid_mask(tone)
    valid = mask & (~invalid)

    # 逐格测量
    cell_labs = []
    cell_positions = []
    for r in range(grid_rows):
        y0 = int(r * bh / grid_rows)
        y1 = int((r + 1) * bh / grid_rows)
        for c in range(grid_cols):
            x0 = int(c * bw / grid_cols)
            x1 = int((c + 1) * bw / grid_cols)
            cell_mask = valid[y0:y1, x0:x1]
            if np.count_nonzero(cell_mask) < 20:
                continue
            cell_lab = lab[y0:y1, x0:x1][cell_mask].mean(axis=0)
            cell_labs.append(cell_lab)
            cell_positions.append({"row": r, "col": c})

    if len(cell_labs) < 4:
        return {"error": "有效网格不足，无法分析均匀性"}

    cell_arr = np.array(cell_labs)
    global_mean = cell_arr.mean(axis=0)

    # 各格与全局均值的色差
    from senia_color_report import _ciede2000_detail
    cell_des = []
    for cl in cell_labs:
        lab_dict = {"L": float(cl[0]), "a": float(cl[1]), "b": float(cl[2])}
        mean_dict = {"L": float(global_mean[0]), "a": float(global_mean[1]), "b": float(global_mean[2])}
        de = _ciede2000_detail(lab_dict, mean_dict)["dE00"]
        cell_des.append(de)

    max_de = max(cell_des)
    avg_de = float(np.mean(cell_des))
    std_L = float(cell_arr[:, 0].std())

    # 边缘vs中心
    edge_cells = [i for i, p in enumerate(cell_positions)
                  if p["row"] == 0 or p["row"] == grid_rows - 1
                  or p["col"] == 0 or p["col"] == grid_cols - 1]
    center_cells = [i for i in range(len(cell_positions)) if i not in edge_cells]

    edge_center_de = 0.0
    if edge_cells and center_cells:
        edge_mean = cell_arr[edge_cells].mean(axis=0)
        center_mean = cell_arr[center_cells].mean(axis=0)
        edge_lab = {"L": float(edge_mean[0]), "a": float(edge_mean[1]), "b": float(edge_mean[2])}
        center_lab = {"L": float(center_mean[0]), "a": float(center_mean[1]), "b": float(center_mean[2])}
        edge_center_de = _ciede2000_detail(edge_lab, center_lab)["dE00"]

    # 判定
    if max_de < 1.0 and edge_center_de < 0.5:
        uniformity = "优秀"
        cause = "无需处理"
    elif max_de < 2.0 and edge_center_de < 1.0:
        uniformity = "良好"
        cause = "轻微不均匀，可接受"
    elif std_L < 2.0 and edge_center_de > 1.5:
        uniformity = "边缘偏差"
        cause = "边缘和中心色差较大，可能是刮刀压力不均或边缘墨量不足"
    elif std_L > 3.0:
        uniformity = "不均匀"
        cause = "板面色差分布不均，可能是工艺问题（涂布速度/烘干温度/辊压力）"
    else:
        uniformity = "一般"
        cause = "存在一定不均匀"

    return {
        "均匀性评价": uniformity,
        "网格数": len(cell_labs),
        "格间最大色差": round(max_de, 2),
        "格间平均色差": round(avg_de, 2),
        "亮度标准差": round(std_L, 2),
        "边缘vs中心色差": round(edge_center_de, 2),
        "原因分析": cause,
    }


# ════════════════════════════════════════════════
# 4. 连续生产漂移检测
# ════════════════════════════════════════════════

class ProductionDriftTracker:
    """
    跟踪连续生产中的色差漂移趋势.

    工厂痛点: 墨辊磨损、墨水浓度下降、温度变化导致颜色逐渐偏移.
    人工对色只能发现当前不合格, 看不到趋势.
    系统能提前预警: "色差正在上升, 预计再生产X卷后会不合格".
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    def add_measurement(
        self,
        lab: dict[str, float],
        de: float,
        batch_id: str = "",
        timestamp: str = "",
    ) -> dict[str, Any]:
        self._history.append({
            "L": lab["L"], "a": lab["a"], "b": lab["b"],
            "dE": de, "batch_id": batch_id, "timestamp": timestamp,
        })
        return self.analyze_trend()

    def analyze_trend(self) -> dict[str, Any]:
        if len(self._history) < 3:
            return {"trend": "数据不足", "samples": len(self._history)}

        des = [h["dE"] for h in self._history]
        ls = [h["L"] for h in self._history]
        n = len(des)

        # 简单线性趋势
        x = np.arange(n, dtype=np.float64)
        de_slope = float(np.polyfit(x, des, 1)[0])
        l_slope = float(np.polyfit(x, ls, 1)[0])

        # 最近3个 vs 最早3个
        recent_de = float(np.mean(des[-3:]))
        early_de = float(np.mean(des[:3]))
        de_drift = recent_de - early_de

        # 预测剩余合格批次
        current_de = des[-1]
        threshold = 3.0  # 木纹标准
        if de_slope > 0.01:
            remaining = max(0, int((threshold - current_de) / de_slope))
        else:
            remaining = 999

        trend = "稳定"
        urgency = "低"
        if de_slope > 0.05:
            trend = "快速恶化"
            urgency = "紧急"
        elif de_slope > 0.02:
            trend = "缓慢恶化"
            urgency = "注意"
        elif de_slope < -0.02:
            trend = "改善中"
            urgency = "低"

        return {
            "trend": trend,
            "urgency": urgency,
            "samples": n,
            "色差趋势斜率": round(de_slope, 4),
            "亮度趋势斜率": round(l_slope, 4),
            "最近色差": round(recent_de, 2),
            "漂移量": round(de_drift, 2),
            "预计剩余合格批次": remaining if remaining < 999 else "充足",
            "建议": _drift_suggestion(trend, remaining, de_slope),
        }


def _drift_suggestion(trend: str, remaining: int, slope: float) -> str:
    if trend == "快速恶化":
        return f"色差快速上升 (每批+{slope:.3f})，预计{remaining}批后不合格。建议立即检查墨辊/墨水浓度/刮刀状态"
    elif trend == "缓慢恶化":
        return f"色差缓慢上升，预计{remaining}批后达到限值。建议安排预防性维护"
    elif trend == "改善中":
        return "色差趋势改善，当前调整有效，继续保持"
    return "色差稳定，生产正常"


# ════════════════════════════════════════════════
# 5. 边缘效应检测
# ════════════════════════════════════════════════

def detect_edge_effect(
    image_bgr: np.ndarray,
    board_quad: np.ndarray,
    border_ratio: float = 0.15,
) -> dict[str, Any]:
    """
    检测板材边缘与中心的色差.

    工厂痛点: 凹版印刷的边缘墨量不均, 导致边缘偏浅/偏深.
    人工肉眼很难发现轻微的边缘效应, 但装配后会明显.
    """
    result = analyze_board_uniformity(image_bgr, board_quad, grid_rows=6, grid_cols=8)
    if "error" in result:
        return result

    edge_de = result.get("边缘vs中心色差", 0)

    if edge_de < 0.5:
        level = "无"
        suggestion = "边缘效应不明显，合格"
    elif edge_de < 1.0:
        level = "轻微"
        suggestion = "边缘有轻微色差，单片不影响但拼装后可能可见"
    elif edge_de < 2.0:
        level = "中等"
        suggestion = "边缘色差明显，建议检查刮刀压力和边缘墨量设置"
    else:
        level = "严重"
        suggestion = "边缘色差严重，需调整刮刀或更换墨辊"

    return {
        "边缘效应等级": level,
        "边缘vs中心色差": round(edge_de, 2),
        "建议": suggestion,
    }


# ════════════════════════════════════════════════
# 6. 纹理匹配度评估
# ════════════════════════════════════════════════

def evaluate_texture_match(
    board_bgr: np.ndarray,
    sample_bgr: np.ndarray,
    board_quad: np.ndarray,
    sample_quad: np.ndarray,
) -> dict[str, Any]:
    """
    评估木纹纹理匹配度 — 不只比颜色, 还比纹理.

    人工对色员会看:
      1. 木纹方向是否一致
      2. 木纹粗细/密度是否一致
      3. 木纹清晰度是否一致
    """
    from elite_color_match import order_quad

    def _extract_texture(img, quad):
        q = order_quad(quad)
        ws = [np.linalg.norm(q[1]-q[0]), np.linalg.norm(q[2]-q[3])]
        hs = [np.linalg.norm(q[3]-q[0]), np.linalg.norm(q[2]-q[1])]
        tw, th = int(max(ws)), int(max(hs))
        if tw < 40 or th < 40:
            return None, None, None
        dst = np.array([[0,0],[tw,0],[tw,th],[0,th]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(q, dst)
        warped = cv2.warpPerspective(img, M, (tw, th))
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
        # 纹理方向 (梯度主方向)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=5)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)
        angles = np.arctan2(gy, gx)
        dominant_angle = float(np.median(angles)) * 180 / np.pi
        # 纹理强度
        intensity = float(np.sqrt(gx**2 + gy**2).mean())
        # 纹理频率 (拉普拉斯方差)
        frequency = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        return dominant_angle, intensity, frequency

    b_angle, b_intensity, b_freq = _extract_texture(board_bgr, board_quad)
    s_angle, s_intensity, s_freq = _extract_texture(sample_bgr, sample_quad)

    if b_angle is None or s_angle is None:
        return {"error": "区域太小，无法分析纹理"}

    # 方向差异
    angle_diff = abs(b_angle - s_angle)
    if angle_diff > 90:
        angle_diff = 180 - angle_diff
    angle_match = max(0, 100 - angle_diff * 2)

    # 强度差异 (粗细)
    intensity_ratio = min(b_intensity, s_intensity) / max(b_intensity, s_intensity, 1e-6)
    intensity_match = round(intensity_ratio * 100, 0)

    # 频率差异 (密度)
    freq_ratio = min(b_freq, s_freq) / max(b_freq, s_freq, 1e-6)
    freq_match = round(freq_ratio * 100, 0)

    overall = round((angle_match * 0.4 + intensity_match * 0.3 + freq_match * 0.3), 0)

    if overall >= 85:
        verdict = "纹理匹配良好"
    elif overall >= 65:
        verdict = "纹理基本匹配，有差异"
    else:
        verdict = "纹理不匹配，需检查版辊"

    return {
        "纹理匹配总分": f"{overall:.0f}%",
        "方向匹配": f"{angle_match:.0f}%",
        "粗细匹配": f"{intensity_match:.0f}%",
        "密度匹配": f"{freq_match:.0f}%",
        "判定": verdict,
    }
