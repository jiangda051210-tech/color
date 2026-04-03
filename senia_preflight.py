"""
SENIA 图像质量预检 — 在分析前检查照片是否可用
=============================================
解决12个生产关键场景:
  - 模糊检测
  - 暗光检测
  - 过曝检测
  - 保护膜/湿板警告
  - 闪光灯检测
  - 镜头遮挡检测

设计原则: 宁可多报警少漏报. 操作员重拍一次只需 5 秒,
但一个错误的对色判定可能导致整批返工.
"""

from __future__ import annotations
from typing import Any
import cv2
import numpy as np


def preflight_check(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    图像质量预检. 在 analyze_photo 之前调用.

    返回:
      ok: bool — 是否可以继续分析
      warnings: list — 警告列表 (可以继续但需注意)
      errors: list — 错误列表 (建议重拍)
      scores: dict — 各项质量评分
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    errors: list[str] = []
    warnings: list[str] = []
    scores: dict[str, float] = {}

    # ── 1. 模糊检测 (Laplacian 方差) ──
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(lap.var())
    scores["sharpness"] = round(blur_score, 1)
    if blur_score < 30:
        errors.append("照片严重模糊，请稳住手机重新拍摄")
    elif blur_score < 80:
        warnings.append("照片轻微模糊，可能影响精度")

    # ── 2. 亮度检测 ──
    mean_brightness = float(gray.mean())
    scores["brightness"] = round(mean_brightness, 1)
    if mean_brightness < 40:
        errors.append("照片太暗，请在光线充足的地方拍摄 (当前亮度={:.0f}, 需要>60)".format(mean_brightness))
    elif mean_brightness < 60:
        warnings.append("照片偏暗，建议打开灯光 (亮度={:.0f})".format(mean_brightness))
    elif mean_brightness > 220:
        warnings.append("照片过亮，请避免强光直射 (亮度={:.0f})".format(mean_brightness))

    # ── 3. 过曝检测 (像素饱和) ──
    overexposed_ratio = float(np.mean(gray > 250))
    scores["overexposed_ratio"] = round(overexposed_ratio, 4)
    if overexposed_ratio > 0.40:
        errors.append("严重过曝 ({:.0f}%)，可能是闪光灯或纯白图片，请重拍".format(overexposed_ratio * 100))
    elif overexposed_ratio > 0.15:
        warnings.append("部分过曝 ({:.0f}%)，白色背景区域会被自动排除".format(overexposed_ratio * 100))
    elif overexposed_ratio > 0.05:
        warnings.append("轻微过曝 ({:.0f}%)".format(overexposed_ratio * 100))

    # ── 4. 欠曝检测 ──
    underexposed_ratio = float(np.mean(gray < 15))
    scores["underexposed_ratio"] = round(underexposed_ratio, 4)
    if underexposed_ratio > 0.3:
        warnings.append("大面积极暗区域 ({:.0f}%)，可能是深色产品或光线不足".format(underexposed_ratio * 100))

    # ── 5. 闪光灯检测 (高亮中心点) ──
    center_region = gray[h//3:2*h//3, w//3:2*w//3]
    center_bright = float(np.mean(center_region > 245))
    if center_bright > 0.1:
        warnings.append("检测到闪光灯高光，请关闭闪光灯")

    # ── 6. 光照均匀性 ──
    # 四个象限亮度比较
    q1 = float(gray[:h//2, :w//2].mean())
    q2 = float(gray[:h//2, w//2:].mean())
    q3 = float(gray[h//2:, :w//2].mean())
    q4 = float(gray[h//2:, w//2:].mean())
    light_range = max(q1, q2, q3, q4) - min(q1, q2, q3, q4)
    scores["lighting_uniformity"] = round(light_range, 1)
    if light_range > 40:
        warnings.append("光照不均匀 (明暗差={:.0f})，建议调整灯光位置或避免窗户侧光".format(light_range))

    # ── 7. 图像尺寸检查 ──
    scores["resolution"] = h * w
    if h * w < 200 * 200:
        errors.append("图片分辨率太低 ({}x{})，请用更高分辨率拍摄".format(w, h))
    elif h * w < 400 * 400:
        warnings.append("图片分辨率偏低 ({}x{})，可能影响精度".format(w, h))

    # ── 8. 颜色通道饱和检测 (保护膜/特殊光源的特征) ──
    b_mean = float(image_bgr[..., 0].mean())
    g_mean = float(image_bgr[..., 1].mean())
    r_mean = float(image_bgr[..., 2].mean())
    # 如果某个通道极端偏离 → 可能有保护膜或特殊光源
    channel_max = max(b_mean, g_mean, r_mean)
    channel_min = min(b_mean, g_mean, r_mean)
    if channel_max - channel_min > 30:
        warnings.append("色彩通道不平衡 (RGB差={:.0f})，可能是保护膜未撕或光源色温偏差大".format(channel_max - channel_min))

    # ── 9. 镜头遮挡检测 (边缘暗角) ──
    border_mean = float(np.concatenate([
        gray[:20, :].ravel(), gray[-20:, :].ravel(),
        gray[:, :20].ravel(), gray[:, -20:].ravel(),
    ]).mean())
    center_mean = float(center_region.mean())
    if border_mean < center_mean * 0.5 and border_mean < 40:
        warnings.append("边缘异常暗，可能手指挡住了镜头")

    # ── 10. 低饱和度检测 (可能是灰卡/参考板误放) ──
    saturation = hsv[..., 1]
    mean_sat = float(saturation.mean())
    scores["saturation"] = round(mean_sat, 1)

    # ── 综合判定 ──
    ok = len(errors) == 0
    quality = "good" if ok and len(warnings) == 0 else "acceptable" if ok else "poor"

    return {
        "ok": ok,
        "quality": quality,
        "errors": errors,
        "warnings": warnings,
        "scores": scores,
        "suggestion": _build_suggestion(errors, warnings),
    }


def _build_suggestion(errors: list[str], warnings: list[str]) -> str:
    """生成操作建议."""
    if errors:
        return "请解决以上问题后重新拍照"
    if len(warnings) >= 3:
        return "多项质量警告，建议在更好的条件下重新拍照以获得更准确的结果"
    if warnings:
        return "可以继续分析，但结果精度可能受影响"
    return "照片质量良好，可以进行分析"


def detect_wet_or_film(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测保护膜或湿板.

    特征:
      - 保护膜: 整体偏蓝/偏冷, 低饱和度, 有规律的反光线
      - 湿板: 整体偏暗, 高光面积大 (镜面反射), 对比度高
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # 镜面反射比例 (湿板特征)
    specular = float(np.mean((hsv[..., 2] > 230) & (hsv[..., 1] < 30)))

    # 蓝色偏移 (保护膜特征)
    b_bias = float(image_bgr[..., 0].mean()) - float(image_bgr[..., 2].mean())

    # 局部对比度 (湿板比干板对比度高)
    local_std = float(cv2.Laplacian(gray, cv2.CV_64F).std())

    result: dict[str, Any] = {"detected": False, "type": None}

    if specular > 0.08 and local_std > 50:
        result = {
            "detected": True,
            "type": "wet_board",
            "message": "⚠️ 检测到镜面反射特征，膜可能是湿的。湿膜颜色比干燥后深 3-5 ΔE，建议干燥后重新检测。",
            "specular_ratio": round(specular, 4),
        }
    elif b_bias > 8 and specular > 0.03:
        result = {
            "detected": True,
            "type": "protective_film",
            "message": "⚠️ 检测到蓝色偏移+反光特征，可能未撕保护膜。保护膜会使色差偏大 2-5 ΔE，请撕掉后重新拍照。",
            "blue_bias": round(b_bias, 2),
        }

    return result
