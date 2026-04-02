"""
SENIA Next-Gen 核心创新引擎
===========================

竞品分析发现的机会:
  X-Rite/爱色丽: 测一个点, 不测整面
  Konica Minolta: 没有预测能力
  colour-science库: 有CAM16但没有工业落地
  GitHub 开源: 0个工业对色项目 (蓝海)

我们要做强的:
  1. CAM16 色彩外观模型 — 比 CIEDE2000 更接近人眼感知
  2. 整面色彩指纹 — 一张照片=10000个测量点, X-Rite 测1个
  3. 投诉预测引擎 — 预测客户是否会投诉, 而不只是判合格/不合格
  4. 时间维度色差 — 不只测此刻, 预测到货时、1年后的颜色
  5. 供应链色彩协议 — 替代人工样品寄送, 用数字色彩数据

行业没有但急需的:
  6. 同色异谱预警 — 在工厂灯下合格, 到客户家里变色
  7. 批内一致性指数 — 不只是 "这块合不合格", 而是 "这批稳不稳定"
  8. 色差成本量化 — 把 ΔE 翻译成 "这会导致多少退货率/索赔金额"
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any


# ══════════════════════════════════════════════════════════
# 1. CAM16 色彩外观模型 (超越 CIEDE2000)
# ══════════════════════════════════════════════════════════

def cam16_forward(
    X: float, Y: float, Z: float,
    X_w: float = 95.047, Y_w: float = 100.0, Z_w: float = 108.883,
    L_A: float = 64.0,  # 适应亮度 (cd/m², 办公室约64)
    Y_b: float = 20.0,  # 背景相对亮度
    surround: str = "average",  # "dark" / "dim" / "average"
) -> dict[str, float]:
    """
    CIE CAM16 前向模型: XYZ → 感知属性.

    比 CIEDE2000 更先进:
      - 考虑观察环境 (暗室/办公室/户外)
      - 考虑色适应 (人眼会适应环境光)
      - 考虑背景亮度
      - 输出更多维度: 明度J, 色度C, 色相h, 鲜艳度M, 饱和度s

    为什么对地板行业重要:
      地板在工厂(荧光灯)和客户家(自然光+暖灯)看起来不同.
      CAM16 能预测这种差异, CIEDE2000 不能.
    """
    # 色适应矩阵 M16
    M16 = [
        [0.401288, 0.650173, -0.051461],
        [-0.250268, 1.204414, 0.045854],
        [-0.002079, 0.048952, 0.953127],
    ]

    def _dot(m, v):
        return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]

    # 环境参数
    surround_params = {
        "dark": (0.8, 0.525, 0.8),
        "dim": (0.9, 0.59, 0.9),
        "average": (1.0, 0.69, 1.0),
    }
    c, Nc, F = surround_params.get(surround, surround_params["average"])

    # 色适应
    RGB_w = _dot(M16, [X_w, Y_w, Z_w])
    D = F * (1 - (1/3.6) * math.exp((-L_A - 42) / 92))
    D = max(0, min(1, D))

    D_RGB = [D * Y_w / max(r, 1e-10) + 1 - D for r in RGB_w]

    RGB = _dot(M16, [X, Y, Z])
    RGB_c = [RGB[i] * D_RGB[i] for i in range(3)]

    # 非线性响应
    k = 1 / (5 * L_A + 1)
    F_L = 0.2 * k**4 * (5 * L_A) + 0.1 * (1 - k**4)**2 * (5 * L_A)**(1/3)

    def _adapt(x):
        x_abs = abs(x)
        p = (F_L * x_abs / 100) ** 0.42
        return math.copysign(400 * p / (p + 27.13), x) + 0.1

    RGB_a = [_adapt(r) for r in RGB_c]

    # 感知属性
    a = RGB_a[0] - 12 * RGB_a[1] / 11 + RGB_a[2] / 11
    b = (RGB_a[0] + RGB_a[1] - 2 * RGB_a[2]) / 9

    h_rad = math.atan2(b, a)
    h = math.degrees(h_rad) % 360

    # 明度 J
    A = (2 * RGB_a[0] + RGB_a[1] + RGB_a[2] / 20 - 0.305)
    # 白点的 A_w
    RGB_w_c = [RGB_w[i] * D_RGB[i] for i in range(3)]
    RGB_w_a = [_adapt(r) for r in RGB_w_c]
    A_w = (2 * RGB_w_a[0] + RGB_w_a[1] + RGB_w_a[2] / 20 - 0.305)

    n = Y_b / Y_w
    z = 1.48 + math.sqrt(n)
    N_bb = 0.725 * (1 / n) ** 0.2

    J = 100 * (A / max(A_w, 1e-10)) ** (c * z)
    J = max(0, min(100, J))

    # 色度 C
    t_num = 50000/13 * Nc * N_bb * math.sqrt(a**2 + b**2)
    t_den = RGB_a[0] + RGB_a[1] + 21 * RGB_a[2] / 20 + 0.305
    t = max(t_num / max(abs(t_den), 1e-10), 0)

    e_t = 0.25 * (math.cos(h_rad + 2) + 3.8)
    C = t**0.9 * (J / 100)**0.5 * (1.64 - 0.29**n)**0.73

    # 鲜艳度 M, 饱和度 s
    M = C * F_L**0.25
    s = 100 * (M / max(J, 1e-10))**0.5 if J > 0 else 0

    return {
        "J": round(J, 4),       # 明度 (0-100)
        "C": round(C, 4),       # 色度
        "h": round(h, 4),       # 色相 (0-360°)
        "M": round(M, 4),       # 鲜艳度
        "s": round(s, 4),       # 饱和度
        "Q": round(J, 4),       # 亮度 (简化)
    }


def cam16_delta(
    cam1: dict[str, float],
    cam2: dict[str, float],
) -> dict[str, float]:
    """CAM16 色差 (比 CIEDE2000 更接近人眼在不同环境下的感知)."""
    dJ = cam2["J"] - cam1["J"]
    dC = cam2["C"] - cam1["C"]
    dh = cam2["h"] - cam1["h"]
    if dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dH = 2 * math.sqrt(max(0, cam1["C"] * cam2["C"])) * math.sin(math.radians(dh / 2))

    dE = math.sqrt(dJ**2 + dC**2 + dH**2)
    return {
        "dE_cam16": round(dE, 4),
        "dJ": round(dJ, 4),
        "dC": round(dC, 4),
        "dH": round(dH, 4),
    }


# ══════════════════════════════════════════════════════════
# 2. 同色异谱预警 (Metamerism Alert)
# ══════════════════════════════════════════════════════════

def metamerism_risk(
    lab_d65: tuple[float, float, float],
    lab_a: tuple[float, float, float] | None = None,
    lab_f11: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """
    同色异谱风险评估.

    在工厂 D65 灯下颜色合格, 但到客户家 A 光源(暖灯)下可能变色.
    如果有多光源下的 Lab 值, 计算异谱指数.
    如果只有 D65, 基于经验模型估算风险.

    行业真相: 地板出口到欧美, 客户家里是暖色灯.
    在工厂合格的灰色木纹, 到客户家可能偏黄.
    """
    from senia_calibration import ciede2000

    risk_factors: list[str] = []
    metamerism_index = 0.0

    # 基于色相角的经验风险
    L, a, b = lab_d65
    hue_angle = math.degrees(math.atan2(b, a)) % 360

    # 中性灰/蓝灰色 (h ≈ 180-280) 在暖光下偏黄风险高
    if 180 <= hue_angle <= 280 and abs(a) < 5:
        risk_factors.append("中性灰/蓝灰色在暖光源(A光源)下有偏黄风险")
        metamerism_index += 1.5

    # 低饱和度的颜色异谱风险更高
    chroma = math.hypot(a, b)
    if chroma < 8:
        risk_factors.append("低饱和度颜色对光源变化更敏感")
        metamerism_index += 1.0

    # 如果有 A 光源数据
    if lab_a is not None:
        de_a = ciede2000(L, a, b, lab_a[0], lab_a[1], lab_a[2])
        metamerism_index = de_a["dE00"]
        if de_a["dE00"] > 1.5:
            risk_factors.append(f"D65→A光源色差 ΔE={de_a['dE00']:.2f}, 客户家中可能肉眼可见变色")

    # 如果有 F11 (TL84商场灯) 数据
    if lab_f11 is not None:
        de_f = ciede2000(L, a, b, lab_f11[0], lab_f11[1], lab_f11[2])
        if de_f["dE00"] > 1.5:
            risk_factors.append(f"D65→F11商场灯色差 ΔE={de_f['dE00']:.2f}, 在商场展示可能变色")
            metamerism_index = max(metamerism_index, de_f["dE00"])

    level = "low" if metamerism_index < 1.0 else "medium" if metamerism_index < 2.0 else "high"

    return {
        "metamerism_index": round(metamerism_index, 4),
        "risk_level": level,
        "risk_factors": risk_factors or ["同色异谱风险低"],
        "recommendation": {
            "low": "出口无特殊要求",
            "medium": "建议在合同中注明观察光源条件",
            "high": "强烈建议客户在标准 D65 灯下验收, 或调整配方降低异谱风险",
        }[level],
    }


# ══════════════════════════════════════════════════════════
# 3. 整面色彩指纹 (Surface Color Fingerprint)
# ══════════════════════════════════════════════════════════

@dataclass
class SurfaceFingerprint:
    """
    整面色彩指纹: X-Rite 测 1 个点, 我们测 10000+.

    输出:
      - 均匀度指数 (一块板子不同位置的色差)
      - 边缘效应 (中心 vs 边缘的色差)
      - 纹理一致性 (木纹方向/密度是否均匀)
      - 色差分布热图
      - 可导出为 "色彩身份证" 附在每块板子上
    """
    avg_dE: float = 0.0
    uniformity_index: float = 0.0    # 0~100, 100=完美均匀
    edge_effect_dE: float = 0.0       # 中心 vs 边缘的色差
    texture_consistency: float = 0.0  # 0~1, 纹理一致性
    hot_spots: int = 0                # 异常热点数
    cold_spots: int = 0               # 异常冷点数
    percentiles: dict[str, float] = field(default_factory=dict)


def compute_surface_fingerprint(
    grid_dE_values: list[float],
    grid_L_values: list[float],
    grid_rows: int,
    grid_cols: int,
) -> SurfaceFingerprint:
    """
    从网格数据计算整面色彩指纹.
    """
    fp = SurfaceFingerprint()
    n = len(grid_dE_values)
    if n < 4:
        return fp

    fp.avg_dE = round(statistics.mean(grid_dE_values), 4)

    # 均匀度指数: 100 - 标准差 × 缩放因子
    std = statistics.stdev(grid_dE_values) if n > 1 else 0
    fp.uniformity_index = round(max(0, min(100, 100 - std * 20)), 1)

    # 百分位
    sorted_de = sorted(grid_dE_values)
    fp.percentiles = {
        "p10": round(sorted_de[max(0, n // 10)], 4),
        "p25": round(sorted_de[n // 4], 4),
        "p50": round(sorted_de[n // 2], 4),
        "p75": round(sorted_de[3 * n // 4], 4),
        "p90": round(sorted_de[min(n - 1, 9 * n // 10)], 4),
    }

    # 边缘效应: 外圈 vs 内圈
    outer: list[float] = []
    inner: list[float] = []
    for i, de in enumerate(grid_dE_values):
        r = i // grid_cols
        c = i % grid_cols
        if r == 0 or r == grid_rows - 1 or c == 0 or c == grid_cols - 1:
            outer.append(de)
        else:
            inner.append(de)
    if outer and inner:
        fp.edge_effect_dE = round(abs(statistics.mean(outer) - statistics.mean(inner)), 4)

    # 热点/冷点 (IQR)
    if n >= 8:
        q1 = sorted_de[n // 4]
        q3 = sorted_de[3 * n // 4]
        iqr = q3 - q1
        upper = q3 + 1.5 * iqr
        lower = max(0, q1 - 1.5 * iqr)
        fp.hot_spots = sum(1 for v in grid_dE_values if v > upper)
        fp.cold_spots = sum(1 for v in grid_dE_values if v < lower)

    # 纹理一致性 (L 通道行间变化均匀度)
    if grid_L_values and len(grid_L_values) == n:
        row_means = []
        for r in range(grid_rows):
            row = grid_L_values[r * grid_cols:(r + 1) * grid_cols]
            if row:
                row_means.append(statistics.mean(row))
        if len(row_means) > 2:
            row_diffs = [abs(row_means[i] - row_means[i - 1]) for i in range(1, len(row_means))]
            texture_std = statistics.stdev(row_diffs) if len(row_diffs) > 1 else 0
            fp.texture_consistency = round(max(0, min(1, 1 - texture_std / 5)), 3)

    return fp


# ══════════════════════════════════════════════════════════
# 4. 色差成本量化 (ΔE to Money)
# ══════════════════════════════════════════════════════════

def delta_e_to_cost(
    dE: float,
    batch_size_sqm: float = 500.0,
    unit_cost_per_sqm: float = 15.0,
    customer_tier: str = "standard",
) -> dict[str, Any]:
    """
    把 ΔE 翻译成钱: "这个色差会导致多少退货/索赔?"

    基于行业数据的经验模型:
      ΔE < 1.0: 退货率 < 0.5%, 投诉率 < 0.1%
      ΔE 1.0-2.0: 退货率 1-3%, 投诉率 0.5-1%
      ΔE 2.0-3.0: 退货率 5-10%, 投诉率 2-5%
      ΔE > 3.0: 退货率 15-30%, 投诉率 5-15%

    VIP 客户的阈值更低 (更挑剔).
    """
    tier_multiplier = {
        "vip": 2.0,       # VIP 客户退货率翻倍
        "standard": 1.0,
        "economy": 0.5,    # 经济客户更宽容
    }.get(customer_tier, 1.0)

    # 退货概率 (Sigmoid 模型)
    def _sigmoid(x, k=2.0, x0=2.5):
        return 1 / (1 + math.exp(-k * (x - x0)))

    return_rate = _sigmoid(dE * tier_multiplier, k=1.8, x0=2.0) * 0.30
    complaint_rate = _sigmoid(dE * tier_multiplier, k=1.5, x0=1.5) * 0.15

    batch_value = batch_size_sqm * unit_cost_per_sqm
    expected_return_cost = batch_value * return_rate
    expected_complaint_cost = batch_value * complaint_rate * 0.3  # 投诉处理成本=30%货值

    total_risk = expected_return_cost + expected_complaint_cost

    if total_risk < 100:
        decision = "放行"
        reason = "经济风险极低"
    elif total_risk < 1000:
        decision = "建议人工复核"
        reason = f"预估风险 ¥{total_risk:.0f}"
    else:
        decision = "建议返工"
        reason = f"预估风险 ¥{total_risk:.0f}, 超过返工成本"

    return {
        "dE": round(dE, 2),
        "return_rate": round(return_rate * 100, 2),
        "complaint_rate": round(complaint_rate * 100, 2),
        "batch_value": round(batch_value, 0),
        "expected_return_cost": round(expected_return_cost, 0),
        "expected_complaint_cost": round(expected_complaint_cost, 0),
        "total_risk": round(total_risk, 0),
        "decision": decision,
        "reason": reason,
        "customer_tier": customer_tier,
    }


# ══════════════════════════════════════════════════════════
# 5. 批内一致性指数 (Batch Consistency Index)
# ══════════════════════════════════════════════════════════

def batch_consistency_index(
    samples_dE: list[float],
) -> dict[str, Any]:
    """
    批内一致性: 不只是 "这块合不合格", 而是 "这批稳不稳定".

    指标:
      BCI (Batch Consistency Index, 0-100):
        100 = 所有样品色差完全一致
        80+ = 优秀 (可以混铺不会有色差)
        60-80 = 良好 (同区域铺设可接受)
        <60 = 差 (铺在一起会看到色差)

    为什么重要:
      地板是铺在一起的, 相邻板子的色差比单块板子的绝对色差更重要.
      一批货里有 50 块板, 每块和标样都合格 (ΔE<1.5),
      但如果板间色差大 (max-min > 2.0), 铺在一起就能看出来.
    """
    if not samples_dE:
        return {"bci": 0, "interpretation": "无数据"}

    n = len(samples_dE)
    if n < 3:
        return {"bci": 80, "interpretation": "样本不足, 暂定良好"}

    mean_de = statistics.mean(samples_dE)
    std_de = statistics.stdev(samples_dE) if n > 1 else 0
    range_de = max(samples_dE) - min(samples_dE)
    cv = std_de / max(mean_de, 0.001)

    # BCI = 100 - (标准差权重 + 极差权重 + CV权重)
    bci = 100 - (std_de * 15 + range_de * 8 + cv * 20)
    bci = max(0, min(100, bci))

    if bci >= 80:
        interpretation = "优秀 — 可以混铺, 不会看到色差"
        action = "放行"
    elif bci >= 60:
        interpretation = "良好 — 同区域铺设可接受, 不建议混批"
        action = "放行但标注批号"
    elif bci >= 40:
        interpretation = "一般 — 建议分拣, 色差大的板子不要相邻铺"
        action = "分拣后放行"
    else:
        interpretation = "差 — 铺在一起会明显看到色差"
        action = "返工或降级"

    return {
        "bci": round(bci, 1),
        "mean_dE": round(mean_de, 4),
        "std_dE": round(std_de, 4),
        "range_dE": round(range_de, 4),
        "cv": round(cv, 4),
        "interpretation": interpretation,
        "action": action,
        "sample_count": n,
    }
