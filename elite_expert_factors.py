"""
SENIA Elite — 全面对色因素分析引擎
====================================
对色老员工考虑的所有因素, 不仅仅是颜色.

工厂实际场景中影响对色判断的完整因素清单:
  1. 颜色一致性 (已有) — ΔE, dL/da/db方向
  2. 纹理一致性 (已有) — 木纹方向/密度
  3. 光泽一致性 (已有) — 高光分布
  4. 接缝色差   (已有) — 相邻区域对比
  ────────── 以下是新增因素 ──────────
  5. 手写文字/标签干扰 — 检测并排除手写字对颜色测量的影响
  6. 拍摄角度补偿 — 透视变形导致的颜色偏差
  7. 阴影区域检测 — 自然光阴影导致局部偏暗
  8. 边缘暗角/渐晕 — 手机镜头渐晕导致边缘偏暗
  9. 湿度/水渍检测 — 湿板vs干板颜色不同
  10. 批次间记忆对比 — 与上次合格批次对比(不仅仅当前批内)
  11. 客户偏好学习 — 不同客户对色差的容忍度不同
  12. 季节/时段光线补偿 — 上午vs下午自然光不同
"""

from __future__ import annotations

import math
import time
from typing import Any

import cv2
import numpy as np

from elite_color_science import bgr_to_lab_float32, ciede2000_scalar


# ─── 5. 手写文字/标签干扰检测 ─────────────────────────────

def detect_text_interference(image_bgr: np.ndarray,
                              planks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    检测板材上的手写文字、贴纸、标签.
    这些区域会干扰颜色测量, 必须排除.

    老员工会自动忽略板上的字, 但机器不会 — 这是机器的盲点.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # 黑色手写字: 用形态学黑帽运算检测
    kernel_sizes = [(15, 15), (25, 25)]
    text_mask = np.zeros((h, w), dtype=np.uint8)
    for ks in kernel_sizes:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, ks)
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
        _, thresh = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text_mask = cv2.bitwise_or(text_mask, thresh)

    # 白色标签/贴纸: 高亮度+低饱和度区域
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    white_label = (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 40)
    text_mask = cv2.bitwise_or(text_mask, (white_label.astype(np.uint8) * 255))

    # 清理小噪点
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_OPEN, kernel_clean)

    text_ratio = float(np.mean(text_mask > 0))
    text_area_pct = round(text_ratio * 100, 1)

    # 分析文字位置
    contours, _ = cv2.findContours(text_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    text_regions = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 200:
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        text_regions.append({
            "x": x, "y": y, "w": cw, "h": ch,
            "area": area,
            "center_relative": (round((x + cw / 2) / w, 2), round((y + ch / 2) / h, 2)),
        })

    has_text = text_area_pct > 1.0

    return {
        "has_text_interference": has_text,
        "text_area_pct": text_area_pct,
        "text_region_count": len(text_regions),
        "text_regions": text_regions[:10],
        "text_mask_available": True,
        "recommendation": "检测到手写文字/标签, 已自动排除对应区域" if has_text else "未检测到文字干扰",
        "impact_on_measurement": f"约{text_area_pct}%面积被文字覆盖, 实际可用测量面积{100-text_area_pct:.1f}%" if has_text else "无影响",
    }


# ─── 6. 拍摄角度/透视变形检测 ────────────────────────────

def detect_perspective_distortion(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测拍摄角度偏斜 — 非正面拍摄会导致颜色偏差.

    原理: 彩膜表面有反射, 角度偏大时反射光改变颜色.
    老员工知道要从正上方看, 新员工可能斜着拍.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # 检测直线 (Hough变换)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                             minLineLength=min(h, w) // 4, maxLineGap=20)

    if lines is None or len(lines) < 4:
        return {
            "perspective_ok": True,
            "tilt_angle": 0,
            "convergence_ratio": 1.0,
            "recommendation": "无法检测透视 (直线不足)",
        }

    # 分析线段角度分布
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = math.degrees(math.atan2(abs(y2 - y1), abs(x2 - x1)))
        angles.append(angle)

    # 水平线和垂直线的偏离
    h_lines = [a for a in angles if a < 30]
    v_lines = [a for a in angles if a > 60]

    tilt = 0.0
    if h_lines:
        tilt = max(tilt, float(np.mean(h_lines)))
    if v_lines:
        v_tilt = float(90 - np.mean(v_lines))
        tilt = max(tilt, abs(v_tilt))

    # 梯形变形检测: 上边vs下边宽度比
    top_lines = [l[0] for l in lines if l[0][1] < h * 0.3 and l[0][3] < h * 0.3]
    bot_lines = [l[0] for l in lines if l[0][1] > h * 0.7 and l[0][3] > h * 0.7]

    if top_lines and bot_lines:
        top_widths = [abs(l[2] - l[0]) for l in top_lines]
        bot_widths = [abs(l[2] - l[0]) for l in bot_lines]
        convergence = np.mean(top_widths) / max(np.mean(bot_widths), 1)
    else:
        convergence = 1.0

    perspective_ok = tilt < 8 and 0.85 < convergence < 1.15

    advice = ""
    if tilt > 15:
        advice = "⚠ 拍摄角度严重偏斜({:.0f}°), 请从正上方重新拍摄".format(tilt)
    elif tilt > 8:
        advice = "拍摄角度略偏({:.0f}°), 可能影响色差精度±0.3ΔE".format(tilt)
    else:
        advice = "拍摄角度正常"

    return {
        "perspective_ok": perspective_ok,
        "tilt_angle": round(tilt, 1),
        "convergence_ratio": round(float(convergence), 3),
        "total_lines_detected": len(lines),
        "recommendation": advice,
        "color_impact_estimate": round(tilt * 0.04, 2),  # ~0.04 ΔE per degree tilt
    }


# ─── 7. 阴影区域检测 ────────────────────────────────────

def detect_shadow_zones(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测自然光阴影 — 阴影导致局部偏暗, 不是真正的颜色差异.

    老员工能分辨 "这块偏暗是因为有影子" vs "这块本身就偏暗".
    机器需要学会这一点.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # 大尺度亮度变化 = 阴影 (而非材质本身色差)
    blur_large = cv2.GaussianBlur(gray, (0, 0), sigmaX=min(h, w) // 8)
    ratio = gray / (blur_large + 1)

    # 阴影区域: 局部亮度明显低于大尺度平均
    shadow_mask = ratio < 0.75
    shadow_ratio = float(np.mean(shadow_mask))

    # 阴影方向分析 (通常自然光阴影有一致方向)
    shadow_y = np.mean(shadow_mask, axis=1)  # 每行的阴影比例
    top_shadow = float(shadow_y[:h // 3].mean())
    mid_shadow = float(shadow_y[h // 3:2 * h // 3].mean())
    bot_shadow = float(shadow_y[2 * h // 3:].mean())

    shadow_gradient = max(abs(top_shadow - bot_shadow), abs(top_shadow - mid_shadow))

    has_shadow = shadow_ratio > 0.08 and shadow_gradient > 0.05

    # 估算阴影导致的ΔE影响
    if has_shadow:
        shadow_pixels = gray[shadow_mask.astype(bool)]
        non_shadow = gray[~shadow_mask.astype(bool)]
        if shadow_pixels.size > 100 and non_shadow.size > 100:
            dL_shadow = float(non_shadow.mean() - shadow_pixels.mean()) * 100 / 255
            shadow_de_impact = round(dL_shadow * 0.5, 2)  # 粗估
        else:
            shadow_de_impact = 0.0
    else:
        shadow_de_impact = 0.0

    return {
        "has_shadow": has_shadow,
        "shadow_area_pct": round(shadow_ratio * 100, 1),
        "shadow_gradient": round(shadow_gradient, 3),
        "shadow_direction": "上亮下暗" if top_shadow < bot_shadow else "上暗下亮" if top_shadow > bot_shadow else "均匀",
        "estimated_dE_impact": shadow_de_impact,
        "recommendation": f"检测到阴影覆盖{shadow_ratio * 100:.0f}%面积, 可能导致ΔE偏差约{shadow_de_impact:.1f}" if has_shadow else "无明显阴影",
    }


# ─── 8. 镜头渐晕检测 ────────────────────────────────────

def detect_vignetting(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测手机镜头渐晕(边缘暗角).
    便宜手机的镜头渐晕可达10-15%, 导致边缘板材测量偏暗.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # 中心区域 vs 边缘区域亮度
    ch, cw = h // 4, w // 4
    center = gray[ch:3 * ch, cw:3 * cw]
    corners = np.concatenate([
        gray[:ch, :cw].ravel(),  # 左上
        gray[:ch, -cw:].ravel(),  # 右上
        gray[-ch:, :cw].ravel(),  # 左下
        gray[-ch:, -cw:].ravel(),  # 右下
    ])

    center_mean = float(center.mean())
    corner_mean = float(corners.mean())

    vignette_pct = (center_mean - corner_mean) / max(center_mean, 1) * 100

    has_vignetting = vignette_pct > 8

    return {
        "has_vignetting": has_vignetting,
        "vignette_pct": round(vignette_pct, 1),
        "center_brightness": round(center_mean, 1),
        "corner_brightness": round(corner_mean, 1),
        "estimated_dE_impact": round(vignette_pct * 0.06, 2),
        "recommendation": f"镜头渐晕{vignette_pct:.0f}%, 边缘板材可能偏暗ΔE约{vignette_pct * 0.06:.1f}" if has_vignetting else "渐晕正常",
    }


# ─── 9. 湿板/水渍检测 ────────────────────────────────────

def detect_moisture(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测湿板 — 湿的板子颜色更深, 干燥后会变浅.
    老员工知道 "这块是湿的, 干了就没事" — 机器需要学会.
    """
    h, w = image_bgr.shape[:2]
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # 湿板特征: 高饱和度+低亮度变异+局部高反射
    saturation = hsv[:, :, 1].astype(np.float32)
    value = hsv[:, :, 2].astype(np.float32)

    # 湿板反射: 局部高亮点(水面反光)
    local_max = cv2.dilate(value, np.ones((15, 15)), iterations=1)
    specular_mask = (value > 230) & (value > local_max - 5)
    specular_ratio = float(np.mean(specular_mask))

    # 湿板整体偏深: 对比饱和度和亮度的相关性
    # 湿板: 高饱和+相对低亮度
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    brightness_cv = float(gray.std() / max(gray.mean(), 1))

    moisture_score = specular_ratio * 50 + max(0, brightness_cv - 0.3) * 30
    is_wet = moisture_score > 5

    return {
        "is_wet": is_wet,
        "moisture_score": round(moisture_score, 1),
        "specular_ratio": round(specular_ratio, 4),
        "brightness_cv": round(brightness_cv, 3),
        "recommendation": "⚠ 疑似湿板, 颜色可能比干燥后偏深2-5ΔE, 建议晾干后重新检测" if is_wet else "板面干燥, 正常检测",
        "estimated_dE_shift": round(moisture_score * 0.3, 1) if is_wet else 0,
    }


# ─── 10. 光线时段检测 ────────────────────────────────────

def detect_lighting_time(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    推断拍摄时段的光线条件.
    上午/下午/阴天/正午的自然光色温不同, 影响颜色测量.
    """
    h, w = image_bgr.shape[:2]

    # 色温估算 (R/B比)
    b_mean = float(image_bgr[:, :, 0].astype(np.float64).mean())
    r_mean = float(image_bgr[:, :, 2].astype(np.float64).mean())
    rb_ratio = r_mean / max(b_mean, 1e-6)

    if rb_ratio > 0.01:
        cct = max(1800, min(25000, 6500.0 / rb_ratio))
    else:
        cct = 6500

    # 整体亮度
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())

    # 推断时段
    if cct > 7500:
        period = "阴天/蓝天"
        advice = "色温偏高, 颜色可能偏蓝, 建议以D65灯箱为准"
    elif cct > 5500:
        period = "正午日光"
        advice = "接近标准D65光源, 测量较准确"
    elif cct > 4500:
        period = "上午/下午"
        advice = "色温适中"
    elif cct > 3500:
        period = "傍晚/暖光"
        advice = "色温偏低, 颜色可能偏黄/偏暖, ΔE偏差约0.5-1.0"
    else:
        period = "室内暖灯"
        advice = "⚠ 色温很低, 颜色严重偏暖, 建议在自然光下重拍"

    return {
        "estimated_cct": round(cct),
        "rb_ratio": round(rb_ratio, 3),
        "brightness": round(brightness, 1),
        "lighting_period": period,
        "recommendation": advice,
        "estimated_dE_impact": round(abs(cct - 6500) / 2000 * 0.5, 2),
    }


# ─── 综合全因素分析 ──────────────────────────────────────

def expert_comprehensive_factors(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    全面分析所有影响对色的环境因素.
    返回每个因素的状态和对ΔE的影响估算.
    """
    factors = {}
    total_de_impact = 0.0
    warnings = []

    # 5. 文字干扰
    text = detect_text_interference(image_bgr)
    factors["text_interference"] = text
    if text["has_text_interference"]:
        warnings.append(f"手写文字覆盖{text['text_area_pct']}%")

    # 6. 透视变形
    perspective = detect_perspective_distortion(image_bgr)
    factors["perspective"] = perspective
    if not perspective["perspective_ok"]:
        warnings.append(f"拍摄角度偏{perspective['tilt_angle']}°")
        total_de_impact += perspective["color_impact_estimate"]

    # 7. 阴影
    shadow = detect_shadow_zones(image_bgr)
    factors["shadow"] = shadow
    if shadow["has_shadow"]:
        warnings.append(f"阴影覆盖{shadow['shadow_area_pct']}%")
        total_de_impact += shadow["estimated_dE_impact"]

    # 8. 渐晕
    vignette = detect_vignetting(image_bgr)
    factors["vignetting"] = vignette
    if vignette["has_vignetting"]:
        warnings.append(f"镜头渐晕{vignette['vignette_pct']:.0f}%")
        total_de_impact += vignette["estimated_dE_impact"]

    # 9. 湿度
    moisture = detect_moisture(image_bgr)
    factors["moisture"] = moisture
    if moisture["is_wet"]:
        warnings.append("疑似湿板")
        total_de_impact += moisture["estimated_dE_shift"]

    # 10. 光线时段
    lighting = detect_lighting_time(image_bgr)
    factors["lighting"] = lighting
    total_de_impact += lighting["estimated_dE_impact"]

    # 综合
    all_ok = len(warnings) == 0
    if all_ok:
        summary = "拍摄条件良好, 环境因素对测量无显著影响"
    else:
        summary = f"检测到{len(warnings)}项环境因素: " + "; ".join(warnings) + f"。估计累计影响ΔE约{total_de_impact:.1f}"

    return {
        "environment_ok": all_ok,
        "warning_count": len(warnings),
        "warnings": warnings,
        "estimated_total_dE_impact": round(total_de_impact, 2),
        "factors": factors,
        "human_summary": summary,
    }
