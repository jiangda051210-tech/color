"""
SENIA M1: iPhone ProRAW + ColorChecker 3×3 CCM 色彩校正
========================================================
把设备间差异和光源漂移一次性补偿到 CIELAB 空间。

核心流程:
  1. 在场景中放置 X-Rite ColorChecker 24色卡
  2. 从 ProRAW (DNG) 解析线性 RGB
  3. 自动定位色卡 24 色块，提取实测 RGB
  4. 用最小二乘法拟合 3×3 色彩校正矩阵 (CCM)
  5. 校正后统一转 CIELAB (D50/D65)

设计要点:
  - 45°/0° 采集几何 (光源45°入射, 相机0°正上方)
  - D65 LED灯箱 (Ra≥95)
  - 所有后续比对在 LAB 空间完成
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ── 标准色彩科学常数 ────────────────────────────────────────

# ColorChecker Classic 24色标准 sRGB 值 (D65, 2° observer)
COLORCHECKER_SRGB_D65: list[tuple[int, int, int]] = [
    (115, 82, 68),    # 1  Dark skin
    (194, 150, 130),  # 2  Light skin
    (98, 122, 157),   # 3  Blue sky
    (87, 108, 67),    # 4  Foliage
    (133, 128, 177),  # 5  Blue flower
    (103, 189, 170),  # 6  Bluish green
    (214, 126, 44),   # 7  Orange
    (80, 91, 166),    # 8  Purplish blue
    (193, 90, 99),    # 9  Moderate red
    (94, 60, 108),    # 10 Purple
    (157, 188, 64),   # 11 Yellow green
    (224, 163, 46),   # 12 Orange yellow
    (56, 61, 150),    # 13 Blue
    (70, 148, 73),    # 14 Green
    (175, 54, 60),    # 15 Red
    (231, 199, 31),   # 16 Yellow
    (187, 86, 149),   # 17 Magenta
    (8, 133, 161),    # 18 Cyan
    (243, 243, 242),  # 19 White (.05*)
    (200, 200, 200),  # 20 Neutral 8
    (160, 160, 160),  # 21 Neutral 6.5
    (122, 122, 121),  # 22 Neutral 5
    (85, 85, 85),     # 23 Neutral 3.5
    (52, 52, 52),     # 24 Black (3.5*)
]

# 标准 Lab 值 (D50, 2° observer) 来自 X-Rite 官方规格
COLORCHECKER_LAB_D50: list[tuple[float, float, float]] = [
    (37.986, 13.555, 14.059),
    (65.711, 18.13, 17.81),
    (49.927, -4.88, -21.925),
    (43.139, -13.095, 21.905),
    (55.112, 8.844, -25.399),
    (70.719, -33.397, -0.199),
    (62.661, 36.067, 57.096),
    (40.02, 10.41, -45.964),
    (51.124, 48.239, 16.248),
    (30.325, 22.976, -21.587),
    (72.532, -23.709, 57.255),
    (71.941, 19.363, 67.857),
    (28.778, 14.179, -50.297),
    (55.261, -38.342, 31.37),
    (42.101, 53.378, 28.19),
    (81.733, 4.039, 79.819),
    (51.935, 49.986, -14.574),
    (51.038, -28.631, -28.638),
    (96.539, -0.425, 1.186),
    (81.257, -0.638, -0.335),
    (66.766, -0.734, -0.504),
    (50.867, -0.153, -0.27),
    (35.656, -0.421, -1.231),
    (20.461, -0.079, -0.973),
]


# ── sRGB ↔ Linear RGB ↔ XYZ ↔ Lab 转换 ──────────────────

def _srgb_to_linear(c: float) -> float:
    """sRGB gamma → linear (0-1 scale)."""
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    """Linear → sRGB gamma (0-1 scale)."""
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def rgb_to_linear(r: int, g: int, b: int) -> tuple[float, float, float]:
    return _srgb_to_linear(r / 255.0), _srgb_to_linear(g / 255.0), _srgb_to_linear(b / 255.0)


def linear_to_xyz_d50(lr: float, lg: float, lb: float) -> tuple[float, float, float]:
    """Linear sRGB → CIE XYZ (D50 adapted via Bradford)."""
    x = lr * 0.4360747 + lg * 0.3850649 + lb * 0.1430804
    y = lr * 0.2225045 + lg * 0.7168786 + lb * 0.0606169
    z = lr * 0.0139322 + lg * 0.0971045 + lb * 0.7141733
    return x, y, z


def linear_to_xyz_d65(lr: float, lg: float, lb: float) -> tuple[float, float, float]:
    """Linear sRGB → CIE XYZ (D65, native sRGB white point)."""
    x = lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375
    y = lr * 0.2126729 + lg * 0.7151522 + lb * 0.0721750
    z = lr * 0.0193339 + lg * 0.1191920 + lb * 0.9503041
    return x, y, z


def xyz_to_lab(x: float, y: float, z: float,
               xn: float = 0.9642, yn: float = 1.0, zn: float = 0.8249) -> tuple[float, float, float]:
    """CIE XYZ → CIELAB. Default illuminant D50."""
    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0
    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return L, a, b


def srgb_to_lab_d50(r: int, g: int, b: int) -> tuple[float, float, float]:
    """sRGB (0-255) → CIELAB (D50)."""
    lr, lg, lb = rgb_to_linear(r, g, b)
    x, y, z = linear_to_xyz_d50(lr, lg, lb)
    return xyz_to_lab(x, y, z, 0.9642, 1.0, 0.8249)


def srgb_to_lab_d65(r: int, g: int, b: int) -> tuple[float, float, float]:
    """sRGB (0-255) → CIELAB (D65)."""
    lr, lg, lb = rgb_to_linear(r, g, b)
    x, y, z = linear_to_xyz_d65(lr, lg, lb)
    return xyz_to_lab(x, y, z, 0.95047, 1.0, 1.08883)


# ── CIEDE2000 (标量版, 已通过 Sharma 34对验证) ─────────────

def ciede2000(L1: float, a1: float, b1: float,
              L2: float, a2: float, b2: float) -> dict[str, float]:
    """
    CIEDE2000 色差, 返回 total + 分量分解.
    经 Sharma (2005) 34对参考数据验证.
    """
    rad = math.pi / 180.0
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - math.sqrt(C_bar ** 7 / (C_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(dhp / 2 * rad)

    Lp = (L1 + L2) / 2
    Cp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hp = (h1p + h2p + 360) / 2
    else:
        hp = (h1p + h2p - 360) / 2

    T = (1 - 0.17 * math.cos((hp - 30) * rad) + 0.24 * math.cos(2 * hp * rad)
         + 0.32 * math.cos((3 * hp + 6) * rad) - 0.20 * math.cos((4 * hp - 63) * rad))
    SL = 1 + 0.015 * (Lp - 50) ** 2 / math.sqrt(20 + (Lp - 50) ** 2)
    SC = 1 + 0.045 * Cp
    SH = 1 + 0.015 * Cp * T
    RT = -2 * math.sqrt(Cp ** 7 / (Cp ** 7 + 25 ** 7)) * math.sin(
        math.radians(60 * math.exp(-((hp - 275) / 25) ** 2)))

    vL, vC, vH = dLp / SL, dCp / SC, dHp / SH
    total = math.sqrt(max(0, vL ** 2 + vC ** 2 + vH ** 2 + RT * vC * vH))

    return {
        "dE00": round(total, 4),
        "dL": round(dLp, 4),
        "dC": round(dCp, 4),
        "dH": round(dHp, 4),
        "dL_norm": round(vL, 4),
        "dC_norm": round(vC, 4),
        "dH_norm": round(vH, 4),
    }


# ── 3×3 CCM 色彩校正矩阵 ─────────────────────────────────

@dataclass
class CalibrationResult:
    ccm: list[list[float]]       # 3×3 矩阵
    rmse: float                  # 残差 RMSE (Lab 空间)
    max_error: float             # 最大单色块误差
    patch_errors: list[float]    # 24色块各自误差
    quality: str                 # "excellent" / "good" / "marginal" / "poor"
    timestamp: str = ""
    device_id: str = ""


def _dot3x3(m: list[list[float]], v: tuple[float, float, float]) -> tuple[float, float, float]:
    """3×3 矩阵 × 3向量."""
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _fit_ccm_core(
    measured: np.ndarray,
    target: np.ndarray,
    alpha: float = 0.0,
) -> np.ndarray:
    """
    Fit a 3x3 CCM via SVD-based least squares with optional Tikhonov regularization.

    Parameters:
        measured: (N, 3) array of measured linear RGB values.
        target:   (N, 3) array of target linear RGB values.
        alpha:    Tikhonov regularization strength (0 = plain least squares).

    Returns:
        (3, 3) CCM matrix such that corrected = measured @ ccm.
    """
    if alpha > 0:
        # Tikhonov: (A^T A + alpha*I) x = A^T b
        ATA = measured.T @ measured + alpha * np.eye(measured.shape[1])
        ATb = measured.T @ target
        ccm = np.linalg.solve(ATA, ATb)
    else:
        # SVD-based least squares (numerically stable)
        ccm, _residuals, _rank, _sv = np.linalg.lstsq(measured, target, rcond=None)
    return ccm


def fit_ccm_least_squares(
    measured_rgb: list[tuple[int, int, int]],
    reference_lab: list[tuple[float, float, float]] | None = None,
    illuminant: str = "D50",
    alpha: float = 0.01,
    reject_outliers: bool = True,
    outlier_threshold: float = 2.5,
) -> CalibrationResult:
    """
    用 SVD / Tikhonov 最小二乘法拟合 3×3 CCM, 含可选离群值剔除.

    输入: 实测 24色块 sRGB 值
    参考: 标准 Lab 值 (默认 X-Rite D50)
    流程: measured_linear_RGB × CCM → corrected_linear_RGB → Lab → 与 reference_Lab 比较

    Parameters:
        measured_rgb:      实测色块 sRGB 值列表.
        reference_lab:     参考 Lab 值 (默认 ColorChecker D50).
        illuminant:        "D50" 或 "D65".
        alpha:             Tikhonov 正则化系数 (0 = 纯最小二乘).
        reject_outliers:   是否剔除离群色块后重新拟合.
        outlier_threshold: 离群值判定倍数 (残差 > threshold * median 时剔除).

    返回 CalibrationResult 含校正矩阵和质量评估.
    """
    if reference_lab is None:
        reference_lab = COLORCHECKER_LAB_D50

    n = min(len(measured_rgb), len(reference_lab))
    if n < 6:
        raise ValueError(f"Need at least 6 color patches, got {n}")

    # 把参考 Lab 反推到目标 linear RGB (近似)
    # 更精确的方法: 直接用标准 sRGB 作为目标
    target_linear = np.array([rgb_to_linear(*COLORCHECKER_SRGB_D65[i]) for i in range(n)])
    measured_linear = np.array([rgb_to_linear(*measured_rgb[i]) for i in range(n)])

    # ── Fix 1 + 2: SVD-based least squares with Tikhonov regularization ──
    ccm = _fit_ccm_core(measured_linear, target_linear, alpha=alpha)

    # ── Fix 3: Outlier rejection ──
    if reject_outliers and n > 6:
        predicted = measured_linear @ ccm
        residuals = np.sqrt(np.sum((predicted - target_linear) ** 2, axis=1))
        median_res = np.median(residuals)
        inlier_mask = residuals < outlier_threshold * median_res
        # Only refit if we still have enough patches after rejection
        if np.sum(inlier_mask) >= 6:
            ccm = _fit_ccm_core(
                measured_linear[inlier_mask],
                target_linear[inlier_mask],
                alpha=alpha,
            )

    # Convert numpy CCM to list-of-lists (transpose: lstsq solves M @ C = T,
    # but _dot3x3 expects CCM[out_ch][in_ch], i.e. corrected = CCM @ measured)
    ccm_T = ccm.T
    ccm_list = [[float(ccm_T[r][c]) for c in range(3)] for r in range(3)]

    # 计算校正误差
    to_lab = srgb_to_lab_d50 if illuminant == "D50" else srgb_to_lab_d65
    patch_errors: list[float] = []
    for i in range(n):
        corrected = _dot3x3(ccm_list, tuple(measured_linear[i]))
        # Linear → sRGB → Lab
        cr = max(0, min(255, int(_linear_to_srgb(corrected[0]) * 255 + 0.5)))
        cg = max(0, min(255, int(_linear_to_srgb(corrected[1]) * 255 + 0.5)))
        cb = max(0, min(255, int(_linear_to_srgb(corrected[2]) * 255 + 0.5)))
        lab = to_lab(cr, cg, cb)
        ref = reference_lab[i]
        de = math.sqrt((lab[0] - ref[0]) ** 2 + (lab[1] - ref[1]) ** 2 + (lab[2] - ref[2]) ** 2)
        patch_errors.append(round(de, 4))

    rmse = math.sqrt(sum(e ** 2 for e in patch_errors) / max(len(patch_errors), 1))
    max_err = max(patch_errors) if patch_errors else 0

    if rmse < 1.5:
        quality = "excellent"
    elif rmse < 3.0:
        quality = "good"
    elif rmse < 5.0:
        quality = "marginal"
    else:
        quality = "poor"

    return CalibrationResult(
        ccm=ccm_list,
        rmse=round(rmse, 4),
        max_error=round(max_err, 4),
        patch_errors=patch_errors,
        quality=quality,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


def apply_ccm(ccm: list[list[float]], r: int, g: int, b: int) -> tuple[int, int, int]:
    """Apply 3×3 CCM to a single pixel (sRGB in, sRGB out)."""
    lin = rgb_to_linear(r, g, b)
    corrected = _dot3x3(ccm, lin)
    return (
        max(0, min(255, int(_linear_to_srgb(corrected[0]) * 255 + 0.5))),
        max(0, min(255, int(_linear_to_srgb(corrected[1]) * 255 + 0.5))),
        max(0, min(255, int(_linear_to_srgb(corrected[2]) * 255 + 0.5))),
    )
