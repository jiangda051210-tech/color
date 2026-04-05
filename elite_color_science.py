"""
SENIA Elite — 统一色彩科学核心模块
====================================
所有色彩转换和色差计算的唯一权威实现。
其他模块应从此处导入，而非各自维护副本。

包含:
  - sRGB ↔ Linear RGB (IEC 61966-2-1)
  - Linear RGB ↔ XYZ (D65/D50)
  - XYZ ↔ CIELAB
  - CIEDE2000 (Sharma 2005, 已通过34对参考数据验证)
  - 标量版和NumPy向量版

精度: float64标量 / float32向量, 无8-bit量化瓶颈
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# ─── 常量 ──────────────────────────────────────────────────

# CIE D65 白点
D65_X, D65_Y, D65_Z = 0.95047, 1.0, 1.08883
# CIE D50 白点
D50_X, D50_Y, D50_Z = 0.96422, 1.0, 0.82521
# sRGB → XYZ (D65) 矩阵 (IEC 61966-2-1)
SRGB_TO_XYZ_D65 = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
], dtype=np.float64)
# LAB 常量
_LAB_EPS = 0.008856  # (6/29)^3
_LAB_KAPPA = 903.3    # (29/6)^2 * 3


# ─── sRGB Gamma ────────────────────────────────────────────

def srgb_to_linear(c: float) -> float:
    """sRGB gamma linearization (IEC 61966-2-1). Input/output in [0,1]."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    """Linear to sRGB gamma compression. Input/output in [0,1]."""
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


# ─── 标量 LAB 转换 ─────────────────────────────────────────

def _lab_f(t: float) -> float:
    return t ** (1.0 / 3.0) if t > _LAB_EPS else (_LAB_KAPPA * t + 16.0) / 116.0


def rgb_to_lab_scalar(r: int, g: int, b: int, illuminant: str = "D65") -> tuple[float, float, float]:
    """sRGB(0-255) → CIELAB. Returns (L*, a*, b*)."""
    lr = srgb_to_linear(r / 255.0)
    lg = srgb_to_linear(g / 255.0)
    lb = srgb_to_linear(b / 255.0)
    x = lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375
    y = lr * 0.2126729 + lg * 0.7151522 + lb * 0.0721750
    z = lr * 0.0193339 + lg * 0.1191920 + lb * 0.9503041
    if illuminant == "D50":
        xn, yn, zn = D50_X, D50_Y, D50_Z
    else:
        xn, yn, zn = D65_X, D65_Y, D65_Z
    L = 116.0 * _lab_f(y / yn) - 16.0
    a = 500.0 * (_lab_f(x / xn) - _lab_f(y / yn))
    b_val = 200.0 * (_lab_f(y / yn) - _lab_f(z / zn))
    return L, a, b_val


# ─── NumPy向量 LAB 转换 ────────────────────────────────────

def bgr_to_lab_float32(image_bgr: np.ndarray) -> np.ndarray:
    """BGR(uint8) → CIELAB(float32). D65白点. 全精度无8-bit量化."""
    img = image_bgr.astype(np.float32) / 255.0
    linear = np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)
    r, g, b = linear[..., 2], linear[..., 1], linear[..., 0]
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xr, yr, zr = x / D65_X, y / D65_Y, z / D65_Z
    fx = np.where(xr > _LAB_EPS, np.cbrt(xr), (_LAB_KAPPA * xr + 16.0) / 116.0)
    fy = np.where(yr > _LAB_EPS, np.cbrt(yr), (_LAB_KAPPA * yr + 16.0) / 116.0)
    fz = np.where(zr > _LAB_EPS, np.cbrt(zr), (_LAB_KAPPA * zr + 16.0) / 116.0)
    lab = np.empty(image_bgr.shape, dtype=np.float32)
    lab[..., 0] = 116.0 * fy - 16.0
    lab[..., 1] = 500.0 * (fx - fy)
    lab[..., 2] = 200.0 * (fy - fz)
    return lab


def lab_to_rgb_scalar(L: float, a: float, b: float) -> tuple[int, int, int]:
    """CIELAB → sRGB(0-255). D65白点."""
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0
    xr = fx**3 if fx**3 > _LAB_EPS else (116.0 * fx - 16.0) / _LAB_KAPPA
    yr = fy**3 if L > _LAB_KAPPA * _LAB_EPS else L / _LAB_KAPPA
    zr = fz**3 if fz**3 > _LAB_EPS else (116.0 * fz - 16.0) / _LAB_KAPPA
    x, y, z = xr * D65_X, yr * D65_Y, zr * D65_Z
    rl = x * 3.2404542 + y * -1.5371385 + z * -0.4985314
    gl = x * -0.9692660 + y * 1.8760108 + z * 0.0415560
    bl = x * 0.0556434 + y * -0.2040259 + z * 1.0572252
    r = int(round(max(0, min(255, linear_to_srgb(max(0, rl)) * 255))))
    g = int(round(max(0, min(255, linear_to_srgb(max(0, gl)) * 255))))
    b_out = int(round(max(0, min(255, linear_to_srgb(max(0, bl)) * 255))))
    return r, g, b_out


# ─── CIEDE2000 标量版 (Sharma 2005) ───────────────────────

def ciede2000_scalar(
    L1: float, a1: float, b1: float,
    L2: float, a2: float, b2: float,
    kL: float = 1.0, kC: float = 1.0, kH: float = 1.0,
) -> dict[str, float]:
    """CIEDE2000 色差 (标量). 已通过Sharma 34对参考数据验证."""
    rad = math.pi / 180.0
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - math.sqrt(C_bar**7 / (C_bar**7 + 25.0**7 + 1e-30)))
    a1p = a1 * (1.0 + G)
    a2p = a2 * (1.0 + G)
    C1p = math.hypot(a1p, b1)
    C2p = math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(dhp / 2.0 * rad)

    Lp = (L1 + L2) / 2.0
    Cp = (C1p + C2p) / 2.0

    if C1p * C2p == 0:
        hp = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hp = (h1p + h2p + 360.0) / 2.0
    else:
        hp = (h1p + h2p - 360.0) / 2.0

    T = (1.0 - 0.17 * math.cos((hp - 30.0) * rad)
         + 0.24 * math.cos(2.0 * hp * rad)
         + 0.32 * math.cos((3.0 * hp + 6.0) * rad)
         - 0.20 * math.cos((4.0 * hp - 63.0) * rad))
    SL = 1.0 + 0.015 * (Lp - 50.0) ** 2 / math.sqrt(20.0 + (Lp - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cp
    SH = 1.0 + 0.015 * Cp * T
    RT = (-2.0 * math.sqrt(Cp**7 / (Cp**7 + 25.0**7 + 1e-30))
          * math.sin(60.0 * math.exp(-((hp - 275.0) / 25.0) ** 2) * rad))

    vL = dLp / (SL * kL)
    vC = dCp / (SC * kC)
    vH = dHp / (SH * kH)
    total = math.sqrt(max(0.0, vL**2 + vC**2 + vH**2 + RT * vC * vH))
    return {"total": total, "dL": vL, "dC": vC, "dH": vH}


# ─── CIEDE2000 NumPy向量版 ─────────────────────────────────

def ciede2000_vectorized(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 色差 (向量). lab1/lab2 shape: (N,3). 返回 (N,) ΔE值."""
    l1, a1, b1 = lab1[:, 0], lab1[:, 1], lab1[:, 2]
    l2, a2, b2 = lab2[:, 0], lab2[:, 1], lab2[:, 2]
    c1 = np.sqrt(a1**2 + b1**2)
    c2 = np.sqrt(a2**2 + b2**2)
    avg_c = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - np.sqrt(avg_c**7 / (avg_c**7 + 25.0**7 + 1e-12)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.sqrt(a1p**2 + b1**2)
    c2p = np.sqrt(a2p**2 + b2**2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    dl = l2 - l1
    dc = c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, dh)
    dh = np.where(dh < -180.0, dh + 360.0, dh)
    dh = np.where((c1p * c2p) == 0, 0.0, dh)
    dhp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2.0))
    avg_l = (l1 + l2) / 2.0
    avg_cp = (c1p + c2p) / 2.0
    hp_sum = h1p + h2p
    avg_hp = np.where(
        np.abs(h1p - h2p) > 180.0,
        np.where(hp_sum < 360.0, (hp_sum + 360.0) / 2.0, (hp_sum - 360.0) / 2.0),
        hp_sum / 2.0,
    )
    avg_hp = np.where((c1p * c2p) == 0, hp_sum, avg_hp)
    t = (1.0 - 0.17 * np.cos(np.radians(avg_hp - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * avg_hp))
         + 0.32 * np.cos(np.radians(3.0 * avg_hp + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * avg_hp - 63.0)))
    delta_theta = 30.0 * np.exp(-((avg_hp - 275.0) / 25.0) ** 2)
    rc = 2.0 * np.sqrt(avg_cp**7 / (avg_cp**7 + 25.0**7 + 1e-12))
    sl = 1.0 + 0.015 * (avg_l - 50.0) ** 2 / np.sqrt(20.0 + (avg_l - 50.0) ** 2)
    sc = 1.0 + 0.045 * avg_cp
    sh = 1.0 + 0.015 * avg_cp * t
    rt = -np.sin(np.radians(2.0 * delta_theta)) * rc
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhp / sh) ** 2 + rt * (dc / sc) * (dhp / sh))
