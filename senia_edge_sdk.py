"""
SENIA Edge SDK — 离线运行的核心引擎
====================================
零依赖 (不需要 numpy/cv2/scipy), 可移植到:
  - iOS (Swift 翻译)
  - Android (Kotlin 翻译)
  - 嵌入式 (C 翻译)
  - WebAssembly (浏览器端)

包含:
  1. sRGB → Lab 转换 (纯数学)
  2. CIEDE2000 色差计算 (已验证)
  3. 三级判定 (PASS/MARGINAL/FAIL)
  4. 偏差方向 (偏红/偏黄/偏暗)
  5. 纹理抑制提底色 (统计方法)
  6. 灰世界白平衡 (算术方法)
  7. 简明调色建议

整个文件 < 300 行, 可直接嵌入任何平台.
"""

from __future__ import annotations

import math
from typing import Any


# ══════════════════════════════════════════════════════════
# 1. 色彩空间转换 (纯数学, 零依赖)
# ══════════════════════════════════════════════════════════

def srgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """sRGB (0-255) → CIELAB (D50). 纯数学, 无依赖."""
    def linearize(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    lr, lg, lb = linearize(r), linearize(g), linearize(b)
    x = lr * 0.4360747 + lg * 0.3850649 + lb * 0.1430804
    y = lr * 0.2225045 + lg * 0.7168786 + lb * 0.0606169
    z = lr * 0.0139322 + lg * 0.0971045 + lb * 0.7141733

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.9642), f(y / 1.0), f(z / 0.8249)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


# ══════════════════════════════════════════════════════════
# 2. CIEDE2000 (经 Sharma 34对验证)
# ══════════════════════════════════════════════════════════

def ciede2000(L1: float, a1: float, b1: float,
              L2: float, a2: float, b2: float) -> float:
    """CIEDE2000 色差, 返回 ΔE00 标量."""
    rad = math.pi / 180
    C1 = math.hypot(a1, b1); C2 = math.hypot(a2, b2)
    Cb = (C1 + C2) / 2; G = 0.5 * (1 - math.sqrt(Cb**7 / (Cb**7 + 25**7)))
    a1p = a1 * (1 + G); a2p = a2 * (1 + G)
    C1p = math.hypot(a1p, b1); C2p = math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp = L2 - L1; dCp = C2p - C1p
    if C1p * C2p == 0: dhp = 0
    elif abs(h2p - h1p) <= 180: dhp = h2p - h1p
    elif h2p - h1p > 180: dhp = h2p - h1p - 360
    else: dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(dhp / 2 * rad)
    Lp = (L1 + L2) / 2; Cp = (C1p + C2p) / 2
    if C1p * C2p == 0: hp = h1p + h2p
    elif abs(h1p - h2p) <= 180: hp = (h1p + h2p) / 2
    elif h1p + h2p < 360: hp = (h1p + h2p + 360) / 2
    else: hp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos((hp - 30) * rad) + 0.24 * math.cos(2 * hp * rad)
         + 0.32 * math.cos((3 * hp + 6) * rad) - 0.20 * math.cos((4 * hp - 63) * rad))
    SL = 1 + 0.015 * (Lp - 50)**2 / math.sqrt(20 + (Lp - 50)**2)
    SC = 1 + 0.045 * Cp; SH = 1 + 0.015 * Cp * T
    RT = -2 * math.sqrt(Cp**7 / (Cp**7 + 25**7)) * math.sin(
        math.radians(60 * math.exp(-((hp - 275) / 25)**2)))
    vL = dLp / SL; vC = dCp / SC; vH = dHp / SH
    return math.sqrt(max(0, vL**2 + vC**2 + vH**2 + RT * vC * vH))


# ══════════════════════════════════════════════════════════
# 3. 灰世界白平衡
# ══════════════════════════════════════════════════════════

def gray_world_wb(pixels: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """灰世界白平衡. 纯算术."""
    if not pixels: return pixels
    n = len(pixels)
    ra = sum(p[0] for p in pixels) / n
    ga = sum(p[1] for p in pixels) / n
    ba = sum(p[2] for p in pixels) / n
    gray = (ra + ga + ba) / 3
    if gray < 1: return pixels
    rs, gs, bs = gray / max(ra, 1), gray / max(ga, 1), gray / max(ba, 1)
    return [(min(255, max(0, int(r * rs + .5))),
             min(255, max(0, int(g * gs + .5))),
             min(255, max(0, int(b * bs + .5)))) for r, g, b in pixels]


# ══════════════════════════════════════════════════════════
# 4. 纹理抑制取底色
# ══════════════════════════════════════════════════════════

def extract_base_color(lab_values: list[tuple[float, float, float]],
                       is_textured: bool = True) -> tuple[float, float, float]:
    """从采样点提取底色. 木纹膜用百分位, 纯色用均值."""
    if not lab_values: return (50.0, 0.0, 0.0)
    n = len(lab_values)
    if not is_textured or n < 5:
        return (sum(v[0] for v in lab_values) / n,
                sum(v[1] for v in lab_values) / n,
                sum(v[2] for v in lab_values) / n)
    Ls = sorted(v[0] for v in lab_values)
    hi = min(n - 1, int(n * 0.85))
    lo = max(0, hi - max(1, n // 5))
    L_base = sum(Ls[lo:hi + 1]) / max(1, hi - lo + 1)
    trim = max(1, n // 10)
    a_vals = sorted(v[1] for v in lab_values)
    b_vals = sorted(v[2] for v in lab_values)
    a_base = sum(a_vals[trim:n - trim]) / max(1, n - 2 * trim)
    b_base = sum(b_vals[trim:n - trim]) / max(1, n - 2 * trim)
    return (round(L_base, 2), round(a_base, 2), round(b_base, 2))


# ══════════════════════════════════════════════════════════
# 5. 异常像素过滤
# ══════════════════════════════════════════════════════════

def filter_outliers(lab_values: list[tuple[float, float, float]],
                    sigma: float = 2.0) -> list[tuple[float, float, float]]:
    """σ 法则过滤异常值 (手写/贴纸/反光)."""
    if len(lab_values) < 10: return lab_values
    n = len(lab_values)
    Ls = [v[0] for v in lab_values]
    L_mean = sum(Ls) / n
    L_var = sum((l - L_mean)**2 for l in Ls) / n
    L_std = max(L_var ** 0.5, 3.0)
    lo, hi = L_mean - sigma * L_std, L_mean + sigma * L_std
    result = [v for v in lab_values if lo <= v[0] <= hi]
    return result if len(result) >= n * 0.5 else lab_values


# ══════════════════════════════════════════════════════════
# 6. 完整离线分析
# ══════════════════════════════════════════════════════════

def analyze_offline(
    ref_pixels: list[tuple[int, int, int]],
    sample_pixels: list[tuple[int, int, int]],
    profile: str = "wood",
    apply_wb: bool = True,
) -> dict[str, Any]:
    """
    完整离线分析 — 零依赖, 可在任何平台运行.

    参数:
      ref_pixels: 标样区域 RGB 采样点
      sample_pixels: 大货区域 RGB 采样点
      profile: wood/solid/stone/metallic/high_gloss
      apply_wb: 是否做灰世界白平衡

    返回: tier, dE00, directions, advice
    """
    if not ref_pixels or not sample_pixels:
        return {"error": "empty pixel data"}

    # 白平衡
    if apply_wb:
        ref_pixels = gray_world_wb(ref_pixels)
        sample_pixels = gray_world_wb(sample_pixels)

    # RGB → Lab
    ref_labs = [srgb_to_lab(r, g, b) for r, g, b in ref_pixels]
    smp_labs = [srgb_to_lab(r, g, b) for r, g, b in sample_pixels]

    # 过滤异常
    ref_labs = filter_outliers(ref_labs)
    smp_labs = filter_outliers(smp_labs)

    # 提取底色
    is_textured = profile in ("wood", "stone")
    ref_base = extract_base_color(ref_labs, is_textured)
    smp_base = extract_base_color(smp_labs, is_textured)

    # CIEDE2000
    dE = ciede2000(ref_base[0], ref_base[1], ref_base[2],
                   smp_base[0], smp_base[1], smp_base[2])
    dL = smp_base[0] - ref_base[0]
    da = smp_base[1] - ref_base[1]
    db = smp_base[2] - ref_base[2]

    # 阈值
    thresholds = {
        "wood": (1.2, 2.8), "solid": (0.8, 2.0), "stone": (1.5, 3.2),
        "metallic": (0.8, 2.2), "high_gloss": (0.6, 1.8),
    }.get(profile, (1.0, 2.5))

    # 三级判定
    if dE <= thresholds[0]:
        tier = "PASS"
    elif dE < thresholds[1]:
        tier = "MARGINAL"
    else:
        tier = "FAIL"

    # 偏差方向
    dirs = []
    if abs(dL) > 0.5: dirs.append("偏亮" if dL > 0 else "偏暗")
    if abs(da) > 0.5: dirs.append("偏红" if da > 0 else "偏绿")
    if abs(db) > 0.5: dirs.append("偏黄" if db > 0 else "偏蓝")

    # 调色建议
    advice = []
    if tier != "PASS":
        if dL > 1.0: advice.append("减白色基料")
        elif dL < -1.0: advice.append("加白或减黑")
        if da > 0.8: advice.append("减红色色精")
        elif da < -0.8: advice.append("减绿或加红")
        if db > 0.8: advice.append("减黄色色精")
        elif db < -0.8: advice.append("减蓝或加黄")
        if dL > 0.8 and db > 0.8: advice.insert(0, "★优先减白")

    return {
        "tier": tier,
        "dE00": round(dE, 4),
        "dL": round(dL, 4),
        "da": round(da, 4),
        "db": round(db, 4),
        "directions": dirs,
        "direction_text": "".join(dirs) or "色差极小",
        "advice": advice or ["无需调整"],
        "ref_lab": list(ref_base),
        "sample_lab": list(smp_base),
        "profile": profile,
    }


# ══════════════════════════════════════════════════════════
# 7. 同步协议 (Edge ↔ Cloud)
# ══════════════════════════════════════════════════════════

def prepare_sync_payload(
    result: dict[str, Any],
    device_id: str = "",
) -> dict[str, Any]:
    """准备上传到云端的同步数据 (轻量, 不含图片)."""
    import hashlib, time
    return {
        "sync_version": "1.0",
        "device_id": device_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tier": result.get("tier", ""),
        "dE00": result.get("dE00", 0),
        "ref_lab": result.get("ref_lab", []),
        "sample_lab": result.get("sample_lab", []),
        "profile": result.get("profile", ""),
        "hash": hashlib.sha256(
            str(result.get("ref_lab", [])).encode() + str(result.get("sample_lab", [])).encode()
        ).hexdigest()[:16],
    }


def apply_cloud_update(
    current_thresholds: dict[str, tuple[float, float]],
    cloud_response: dict[str, Any],
) -> dict[str, tuple[float, float]]:
    """应用云端推送的阈值更新."""
    updates = cloud_response.get("threshold_updates", {})
    result = dict(current_thresholds)
    for profile, vals in updates.items():
        if profile in result and isinstance(vals, dict):
            pass_dE = vals.get("pass_dE", result[profile][0])
            marginal_dE = vals.get("marginal_dE", result[profile][1])
            result[profile] = (
                max(0.3, min(5.0, pass_dE)),
                max(0.8, min(8.0, marginal_dE)),
            )
    return result
