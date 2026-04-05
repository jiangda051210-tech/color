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
from functools import lru_cache
from typing import Any


# ══════════════════════════════════════════════════════════
# 1. CAM16 色彩外观模型 (超越 CIEDE2000)
# ══════════════════════════════════════════════════════════

# 色适应矩阵 M16 (模块级常量, 避免每次调用重建)
_M16 = [
    [0.401288, 0.650173, -0.051461],
    [-0.250268, 1.204414, 0.045854],
    [-0.002079, 0.048952, 0.953127],
]

# 缓存 M16 逆矩阵 (用于逆变换)
def _invert_3x3(m):
    """3x3 矩阵求逆 (Cramer's rule)."""
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-15:
        raise ValueError("Singular matrix")
    inv_det = 1.0 / det
    return [
        [(e * i - f * h) * inv_det, (c * h - b * i) * inv_det, (b * f - c * e) * inv_det],
        [(f * g - d * i) * inv_det, (a * i - c * g) * inv_det, (c * d - a * f) * inv_det],
        [(d * h - e * g) * inv_det, (b * g - a * h) * inv_det, (a * e - b * d) * inv_det],
    ]

_M16_INV = _invert_3x3(_M16)

# 环境参数 (模块级常量)
_SURROUND_PARAMS = {
    "dark": (0.8, 0.525, 0.8),
    "dim": (0.9, 0.59, 0.9),
    "average": (1.0, 0.69, 1.0),
}


def _dot3(m, v):
    """3x3 matrix × 3-vector dot product."""
    return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]


def _cam16_viewing_conditions(
    X_w: float, Y_w: float, Z_w: float,
    L_A: float, Y_b: float, surround: str,
):
    """Compute all viewing-condition-dependent parameters (cacheable)."""
    c, Nc, F = _SURROUND_PARAMS.get(surround, _SURROUND_PARAMS["average"])

    RGB_w = _dot3(_M16, [X_w, Y_w, Z_w])

    # Proper chromatic adaptation degree (D factor)
    # D depends on surround F and adapting luminance L_A
    D = F * (1 - (1 / 3.6) * math.exp((-L_A - 42) / 92))
    D = max(0.0, min(1.0, D))

    D_RGB = [D * Y_w / max(r, 1e-10) + 1 - D for r in RGB_w]

    k = 1 / (5 * L_A + 1)
    F_L = 0.2 * k**4 * (5 * L_A) + 0.1 * (1 - k**4)**2 * (5 * L_A) ** (1 / 3)

    n = Y_b / Y_w
    z = 1.48 + math.sqrt(n)
    N_bb = 0.725 * (1 / n) ** 0.2
    N_cb = N_bb  # 在 CAM16 中 N_cb == N_bb

    def _adapt(x):
        x_abs = abs(x)
        p = (F_L * x_abs / 100) ** 0.42
        return math.copysign(400 * p / (p + 27.13), x) + 0.1

    RGB_w_c = [RGB_w[i] * D_RGB[i] for i in range(3)]
    RGB_w_a = [_adapt(r) for r in RGB_w_c]
    A_w = 2 * RGB_w_a[0] + RGB_w_a[1] + RGB_w_a[2] / 20 - 0.305

    return {
        "c": c, "Nc": Nc, "F": F, "D": D, "D_RGB": D_RGB,
        "F_L": F_L, "n": n, "z": z, "N_bb": N_bb, "N_cb": N_cb,
        "A_w": A_w, "_adapt": _adapt,
    }


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
    vc = _cam16_viewing_conditions(X_w, Y_w, Z_w, L_A, Y_b, surround)
    c = vc["c"]
    Nc, D_RGB, F_L = vc["Nc"], vc["D_RGB"], vc["F_L"]
    n, z, N_bb, A_w = vc["n"], vc["z"], vc["N_bb"], vc["A_w"]
    _adapt = vc["_adapt"]

    # Guard against negative XYZ values
    X, Y, Z = max(X, 0.0), max(Y, 0.0), max(Z, 0.0)
    RGB = _dot3(_M16, [X, Y, Z])
    RGB_c = [RGB[i] * D_RGB[i] for i in range(3)]
    RGB_a = [_adapt(r) for r in RGB_c]
    # Clamp adapted RGB responses to prevent negative values propagating
    RGB_a = [max(r, 0.0) for r in RGB_a]

    # 感知属性
    a = RGB_a[0] - 12 * RGB_a[1] / 11 + RGB_a[2] / 11
    b = (RGB_a[0] + RGB_a[1] - 2 * RGB_a[2]) / 9

    h_rad = math.atan2(b, a)
    h = math.degrees(h_rad) % 360

    # 明度 J
    A = 2 * RGB_a[0] + RGB_a[1] + RGB_a[2] / 20 - 0.305

    J = 100 * (A / max(A_w, 1e-10)) ** (c * z)
    J = max(0.0, min(100.0, J))

    # 色度 C
    t_num = 50000 / 13 * Nc * N_bb * math.sqrt(a**2 + b**2)
    t_den = RGB_a[0] + RGB_a[1] + 21 * RGB_a[2] / 20 + 0.305
    t = max(t_num / max(abs(t_den), 1e-10), 0)

    e_t = 0.25 * (math.cos(h_rad + 2) + 3.8)
    C = t**0.9 * (J / 100)**0.5 * (1.64 - 0.29**n)**0.73

    # 鲜艳度 M, 饱和度 s, 亮度 Q
    M = C * F_L**0.25
    s = 100 * (M / max(J, 1e-10))**0.5 if J > 0 else 0.0
    Q = (4.0 / c) * (J / 100.0)**0.5 * (A_w + 4.0) * F_L**0.25

    return {
        "J": round(J, 4),       # 明度 (0-100)
        "C": round(C, 4),       # 色度
        "h": round(h, 4),       # 色相 (0-360°)
        "M": round(M, 4),       # 鲜艳度
        "s": round(s, 4),       # 饱和度
        "Q": round(Q, 4),       # 亮度 (proper CAM16 brightness)
    }


def cam16_inverse(
    J: float, C: float, h: float,
    X_w: float = 95.047, Y_w: float = 100.0, Z_w: float = 108.883,
    L_A: float = 64.0,
    Y_b: float = 20.0,
    surround: str = "average",
) -> tuple[float, float, float]:
    """
    CIE CAM16 逆变换: (J, C, h) → XYZ.

    支持完整的 CAM16 往返 (round-trip):
      XYZ → cam16_forward → (J,C,h) → cam16_inverse → XYZ'
      XYZ' ≈ XYZ (数值精度内).

    用途: 从感知属性反算 XYZ, 用于色彩合成和色域映射.
    """
    vc = _cam16_viewing_conditions(X_w, Y_w, Z_w, L_A, Y_b, surround)
    c_sur = vc["c"]
    Nc, D_RGB, F_L = vc["Nc"], vc["D_RGB"], vc["F_L"]
    n, z, N_bb = vc["n"], vc["z"], vc["N_bb"]
    A_w = vc["A_w"]

    h_rad = math.radians(h)

    # 从 J 恢复 A
    J_clamped = max(J, 1e-10)
    A = A_w * (J_clamped / 100.0) ** (1.0 / (c_sur * z))

    # 从 C 恢复 t
    e_t = 0.25 * (math.cos(h_rad + 2) + 3.8)
    J_root = (J_clamped / 100.0) ** 0.5
    n_factor = (1.64 - 0.29**n) ** 0.73
    t = 0.0
    if J_root > 1e-10 and n_factor > 1e-10:
        t = (C / (J_root * n_factor)) ** (1.0 / 0.9)

    # 从 t 和 h 恢复 a, b (adapted opponent signals)
    cos_h = math.cos(h_rad)
    sin_h = math.sin(h_rad)

    # A = 2*R_a + G_a + B_a/20 - 0.305
    # p2 = A/N_bb + 0.305
    p2 = A / max(N_bb, 1e-10) + 0.305

    # Solve for a, b from t, h, p2
    # Using the CAM16 equations for a, b recovery
    r = 23 * (p2 + 0.305) * t / (23 * p2 + 11 * t * cos_h + 108 * t * sin_h)
    a_sig = r * cos_h
    b_sig = r * sin_h

    # Recover RGB_a from a, b, p2
    # a = R_a - 12*G_a/11 + B_a/11
    # b = (R_a + G_a - 2*B_a)/9
    # p2 = 2*R_a + G_a + B_a/20
    R_a = p2 / 1.0 + (460 * a_sig + 451 * b_sig) / 1403
    G_a = p2 / 1.0 + (-891 * a_sig - 261 * b_sig) / 1403
    B_a = p2 / 1.0 + (-220 * a_sig - 6300 * b_sig) / 1403

    # Inverse nonlinear adaptation
    def _unadapt(x_a):
        x_a_shifted = x_a - 0.1
        val = 27.13 * abs(x_a_shifted) / (400 - abs(x_a_shifted))
        val = max(val, 0.0)
        return math.copysign(100.0 / F_L * val ** (1.0 / 0.42), x_a_shifted)

    RC = _unadapt(R_a)
    GC = _unadapt(G_a)
    BC = _unadapt(B_a)

    # Undo chromatic adaptation
    RGB = [RC / max(D_RGB[0], 1e-10), GC / max(D_RGB[1], 1e-10), BC / max(D_RGB[2], 1e-10)]

    # M16_inv @ RGB → XYZ
    XYZ = _dot3(_M16_INV, RGB)
    # Prevent negative XYZ values from propagating
    return (max(XYZ[0], 0.0), max(XYZ[1], 0.0), max(XYZ[2], 0.0))


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


def cam16_ucs_distance(
    cam1: dict[str, float],
    cam2: dict[str, float],
    K_L: float = 1.0,
    c1: float = 0.007,
    c2: float = 0.0228,
) -> float:
    """
    CAM16-UCS 均匀色彩空间距离 (比 CIEDE2000 更感知均匀).

    CAM16-UCS 将 CAM16 的 J, M, h 投影到均匀空间:
      J' = (1+100*c1)*J / (1+c1*J)
      M' = (1/c2)*ln(1+c2*M)
      a' = M'*cos(h), b' = M'*sin(h)
      dE = sqrt((dJ'/K_L)^2 + da'^2 + db'^2)

    参数:
      K_L=1.0, c1=0.007, c2=0.0228 对应 CAM16-UCS (Li et al. 2017)
    """
    J1, M1, h1 = cam1["J"], cam1["M"], cam1["h"]
    J2, M2, h2 = cam2["J"], cam2["M"], cam2["h"]

    # J' 均匀明度
    Jp1 = (1 + 100 * c1) * J1 / (1 + c1 * J1) if J1 > 0 else 0.0
    Jp2 = (1 + 100 * c1) * J2 / (1 + c1 * J2) if J2 > 0 else 0.0

    # M' 均匀鲜艳度
    Mp1 = (1.0 / c2) * math.log(1 + c2 * M1) if M1 > 0 else 0.0
    Mp2 = (1.0 / c2) * math.log(1 + c2 * M2) if M2 > 0 else 0.0

    # 投影到 a', b'
    h1_rad = math.radians(h1)
    h2_rad = math.radians(h2)
    ap1, bp1 = Mp1 * math.cos(h1_rad), Mp1 * math.sin(h1_rad)
    ap2, bp2 = Mp2 * math.cos(h2_rad), Mp2 * math.sin(h2_rad)

    dE_ucs = math.sqrt(((Jp2 - Jp1) / K_L) ** 2 + (ap2 - ap1) ** 2 + (bp2 - bp1) ** 2)
    return round(dE_ucs, 4)


# ══════════════════════════════════════════════════════════
# 2. 同色异谱预警 (Metamerism Alert)
# ══════════════════════════════════════════════════════════

def metamerism_risk(
    lab_d65: tuple[float, float, float],
    lab_a: tuple[float, float, float] | None = None,
    lab_f11: tuple[float, float, float] | None = None,
    lab_f2: tuple[float, float, float] | None = None,
    lab_led_4000k: tuple[float, float, float] | None = None,
    lab_led_6500k: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """
    同色异谱风险评估 (增强版).

    在工厂 D65 灯下颜色合格, 但到客户家 A 光源(暖灯)下可能变色.
    如果有多光源下的 Lab 值, 计算异谱指数.
    如果只有 D65, 基于经验模型估算风险.

    增强:
      - 支持 5 种光源: A, F11, F2, LED_4000K, LED_6500K
      - 光谱重叠度量: 基于色相角差异计算敏感区域偏移
      - CAM16 感知距离 (比 Bradford+CIEDE2000 更准确)
      - 按风险优先级排序的建议

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

    # 所有光源数据: (name, lab_data, description)
    illuminant_data = [
        ("A", lab_a, "A光源(暖灯2856K)", "客户家中可能肉眼可见变色"),
        ("F11", lab_f11, "F11商场灯(TL84)", "在商场展示可能变色"),
        ("F2", lab_f2, "F2冷白荧光灯", "办公/学校环境可能变色"),
        ("LED_4000K", lab_led_4000k, "LED 4000K(中性白)", "现代家居LED灯下可能变色"),
        ("LED_6500K", lab_led_6500k, "LED 6500K(冷白)", "工业/办公LED灯下可能变色"),
    ]

    # 按风险排序: 记录每种光源的色差
    illuminant_risks: list[dict[str, Any]] = []

    # CAM16 参考色 (D65 条件)
    # 近似 Lab→XYZ, clamped to prevent negative values
    cam16_ref = cam16_forward(
        max(L * 0.95047, 0.0), max(L, 0.0), max(L * 1.08883, 0.0),
    )

    for illum_name, lab_data, desc, warning in illuminant_data:
        if lab_data is None:
            continue

        # CIEDE2000 色差
        de_result = ciede2000(L, a, b, lab_data[0], lab_data[1], lab_data[2])
        de_val = de_result["dE00"]

        # CAM16 感知距离 (更准确的环境适应比较)
        cam16_illum = cam16_forward(
            max(lab_data[0] * 0.95047, 0.0), max(lab_data[0], 0.0), max(lab_data[0] * 1.08883, 0.0),
        )
        cam16_de = cam16_ucs_distance(cam16_ref, cam16_illum)

        # 光谱重叠度量: 色相角偏移量 (敏感区域)
        hue_illum = math.degrees(math.atan2(lab_data[2], lab_data[1])) % 360
        hue_shift = abs(hue_angle - hue_illum)
        if hue_shift > 180:
            hue_shift = 360 - hue_shift
        spectral_overlap = max(0.0, 1.0 - hue_shift / 30.0)  # 1.0=完全重叠, 0=大偏移

        # 综合风险 = max(CIEDE2000, CAM16-UCS) 加权
        combined_risk = max(de_val, cam16_de * 0.8)

        illuminant_risks.append({
            "illuminant": illum_name,
            "dE00": round(de_val, 4),
            "cam16_ucs_dE": cam16_de,
            "hue_shift": round(hue_shift, 2),
            "spectral_overlap": round(spectral_overlap, 3),
            "combined_risk": round(combined_risk, 4),
        })

        if de_val > 1.5:
            risk_factors.append(f"D65→{desc}色差 ΔE={de_val:.2f}, {warning}")
        metamerism_index = max(metamerism_index, combined_risk)

    # 按风险排序 (最高风险在前)
    illuminant_risks.sort(key=lambda x: x["combined_risk"], reverse=True)

    level = "low" if metamerism_index < 1.0 else "medium" if metamerism_index < 2.0 else "high"

    # 确定最高风险光源
    highest_risk_illuminant = illuminant_risks[0]["illuminant"] if illuminant_risks else None

    recommendation = {
        "low": "出口无特殊要求",
        "medium": "建议在合同中注明观察光源条件",
        "high": "强烈建议客户在标准 D65 灯下验收, 或调整配方降低异谱风险",
    }[level]

    # 如果有明确的最高风险光源, 添加优先级建议
    priority_note = None
    if highest_risk_illuminant and illuminant_risks:
        top = illuminant_risks[0]
        if top["combined_risk"] > 1.5:
            priority_note = (
                f"最高风险光源: {top['illuminant']} "
                f"(ΔE00={top['dE00']}, CAM16-UCS={top['cam16_ucs_dE']}, "
                f"色相偏移={top['hue_shift']}°)"
            )

    return {
        "metamerism_index": round(metamerism_index, 4),
        "risk_level": level,
        "risk_factors": risk_factors or ["同色异谱风险低"],
        "recommendation": recommendation,
        "priority_note": priority_note,
        "illuminant_risks": illuminant_risks,
        "highest_risk_illuminant": highest_risk_illuminant,
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
      - GLCM 纹理特征 (对比度, 能量, 同质性, 相关性)
      - 空间频率分析 (主频率)
      - 色差梯度图 (检测 banding)
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
    # GLCM 纹理特征
    glcm_contrast: float = 0.0
    glcm_energy: float = 0.0
    glcm_homogeneity: float = 0.0
    glcm_correlation: float = 0.0
    # 空间频率分析
    dominant_frequency: float = 0.0    # 主频率 (cycles per grid width)
    frequency_energy: float = 0.0      # 主频率能量占比
    # 色差梯度 (banding 检测)
    max_gradient: float = 0.0          # 最大相邻网格色差变化
    avg_gradient: float = 0.0          # 平均梯度
    banding_risk: str = "low"          # "low" / "medium" / "high"


def _compute_glcm_features(grid_values: list[float], rows: int, cols: int) -> dict[str, float]:
    """
    计算 GLCM (Gray-Level Co-occurrence Matrix) 纹理特征.

    将连续值量化到离散级别, 构建共现矩阵, 提取:
      - contrast: 纹理对比度 (值差异的加权和)
      - energy: 纹理能量/均匀性 (概率平方和, 1=完全均匀)
      - homogeneity: 同质性 (值相近的概率)
      - correlation: 相关性 (线性依赖程度, -1~1)
    """
    n_levels = 8  # 量化级别
    if not grid_values or len(grid_values) < 4:
        return {"contrast": 0.0, "energy": 0.0, "homogeneity": 0.0, "correlation": 0.0}

    # 量化到 0..n_levels-1
    v_min = min(grid_values)
    v_max = max(grid_values)
    v_range = v_max - v_min
    if v_range < 1e-10:
        return {"contrast": 0.0, "energy": 1.0, "homogeneity": 1.0, "correlation": 0.0}

    quantized = [min(n_levels - 1, int((v - v_min) / v_range * (n_levels - 1) + 0.5)) for v in grid_values]

    # 构建 GLCM (水平方向, offset=1)
    glcm = [[0.0] * n_levels for _ in range(n_levels)]
    count = 0
    for r in range(rows):
        for c in range(cols - 1):
            idx = r * cols + c
            idx_next = r * cols + c + 1
            if idx < len(quantized) and idx_next < len(quantized):
                i, j = quantized[idx], quantized[idx_next]
                glcm[i][j] += 1
                glcm[j][i] += 1  # 对称
                count += 2

    # 归一化
    if count > 0:
        for i in range(n_levels):
            for j in range(n_levels):
                glcm[i][j] /= count

    # 提取特征
    contrast = 0.0
    energy = 0.0
    homogeneity = 0.0

    # 用于 correlation 的统计量
    mu_i = 0.0
    mu_j = 0.0
    for i in range(n_levels):
        for j in range(n_levels):
            p = glcm[i][j]
            mu_i += i * p
            mu_j += j * p

    sigma_i = 0.0
    sigma_j = 0.0
    correlation_num = 0.0

    for i in range(n_levels):
        for j in range(n_levels):
            p = glcm[i][j]
            contrast += (i - j) ** 2 * p
            energy += p ** 2
            homogeneity += p / (1 + abs(i - j))
            sigma_i += (i - mu_i) ** 2 * p
            sigma_j += (j - mu_j) ** 2 * p
            correlation_num += (i - mu_i) * (j - mu_j) * p

    sigma_i = math.sqrt(sigma_i)
    sigma_j = math.sqrt(sigma_j)
    correlation = correlation_num / max(sigma_i * sigma_j, 1e-10) if sigma_i > 1e-10 and sigma_j > 1e-10 else 0.0

    return {
        "contrast": round(contrast, 4),
        "energy": round(energy, 4),
        "homogeneity": round(homogeneity, 4),
        "correlation": round(max(-1.0, min(1.0, correlation)), 4),
    }


def _compute_spatial_frequency(grid_values: list[float], rows: int, cols: int) -> tuple[float, float]:
    """
    空间频率分析: 用 DFT 计算功率谱并报告主频率.

    返回 (dominant_frequency, energy_ratio):
      dominant_frequency: 主频率 (cycles per grid width, 0=DC)
      energy_ratio: 主频率能量 / 总能量
    """
    n = len(grid_values)
    if n < 4:
        return 0.0, 0.0

    mean_val = statistics.mean(grid_values)
    centered = [v - mean_val for v in grid_values]

    # 沿行方向做 1D DFT (检测水平周期性)
    # 使用 cols 作为主方向
    freq_power: dict[int, float] = {}
    for r in range(rows):
        row_data = centered[r * cols:(r + 1) * cols]
        if len(row_data) < 2:
            continue
        row_len = len(row_data)
        # DFT (仅正频率)
        for k in range(1, row_len // 2 + 1):
            real = sum(row_data[j] * math.cos(2 * math.pi * k * j / row_len) for j in range(row_len))
            imag = sum(row_data[j] * math.sin(2 * math.pi * k * j / row_len) for j in range(row_len))
            power = real**2 + imag**2
            freq_power[k] = freq_power.get(k, 0.0) + power

    if not freq_power:
        return 0.0, 0.0

    total_power = sum(freq_power.values())
    if total_power < 1e-10:
        return 0.0, 0.0

    dominant_k = max(freq_power, key=freq_power.get)
    energy_ratio = freq_power[dominant_k] / total_power

    return round(float(dominant_k), 2), round(energy_ratio, 4)


def _compute_gradient_map(grid_dE_values: list[float], rows: int, cols: int) -> tuple[float, float, str]:
    """
    色差梯度图: 测量相邻网格之间色差变化, 检测 banding.

    返回 (max_gradient, avg_gradient, banding_risk).
    """
    gradients: list[float] = []
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            if idx >= len(grid_dE_values):
                continue
            val = grid_dE_values[idx]
            # 水平梯度
            if c + 1 < cols:
                idx_right = r * cols + c + 1
                if idx_right < len(grid_dE_values):
                    gradients.append(abs(val - grid_dE_values[idx_right]))
            # 垂直梯度
            if r + 1 < rows:
                idx_below = (r + 1) * cols + c
                if idx_below < len(grid_dE_values):
                    gradients.append(abs(val - grid_dE_values[idx_below]))

    if not gradients:
        return 0.0, 0.0, "low"

    max_grad = max(gradients)
    avg_grad = statistics.mean(gradients)

    # Banding 检测: 如果行间梯度远大于行内梯度 → banding
    row_gradients: list[float] = []
    col_gradients: list[float] = []
    for r in range(rows):
        for c in range(cols - 1):
            idx1 = r * cols + c
            idx2 = r * cols + c + 1
            if idx1 < len(grid_dE_values) and idx2 < len(grid_dE_values):
                row_gradients.append(abs(grid_dE_values[idx1] - grid_dE_values[idx2]))
    for r in range(rows - 1):
        for c in range(cols):
            idx1 = r * cols + c
            idx2 = (r + 1) * cols + c
            if idx1 < len(grid_dE_values) and idx2 < len(grid_dE_values):
                col_gradients.append(abs(grid_dE_values[idx1] - grid_dE_values[idx2]))

    # 如果某个方向梯度显著大于另一个 → banding
    avg_row_grad = statistics.mean(row_gradients) if row_gradients else 0.0
    avg_col_grad = statistics.mean(col_gradients) if col_gradients else 0.0
    anisotropy = abs(avg_row_grad - avg_col_grad) / max(avg_row_grad + avg_col_grad, 1e-10)

    if max_grad > 1.5 and anisotropy > 0.4:
        banding_risk = "high"
    elif max_grad > 0.8 or anisotropy > 0.3:
        banding_risk = "medium"
    else:
        banding_risk = "low"

    return round(max_grad, 4), round(avg_grad, 4), banding_risk


def compute_surface_fingerprint(
    grid_dE_values: list[float],
    grid_L_values: list[float],
    grid_rows: int,
    grid_cols: int,
) -> SurfaceFingerprint:
    """
    从网格数据计算整面色彩指纹.

    增强功能:
      - GLCM 纹理特征 (对比度, 能量, 同质性, 相关性)
      - 空间频率分析 (DFT 主频率)
      - 色差梯度图 (banding 检测)
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

    # GLCM 纹理特征 (基于 dE 网格)
    glcm_feats = _compute_glcm_features(grid_dE_values, grid_rows, grid_cols)
    fp.glcm_contrast = glcm_feats["contrast"]
    fp.glcm_energy = glcm_feats["energy"]
    fp.glcm_homogeneity = glcm_feats["homogeneity"]
    fp.glcm_correlation = glcm_feats["correlation"]

    # 空间频率分析
    fp.dominant_frequency, fp.frequency_energy = _compute_spatial_frequency(
        grid_dE_values, grid_rows, grid_cols,
    )

    # 色差梯度图 (banding 检测)
    fp.max_gradient, fp.avg_gradient, fp.banding_risk = _compute_gradient_map(
        grid_dE_values, grid_rows, grid_cols,
    )

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
