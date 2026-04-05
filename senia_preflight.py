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
  - 户外环境检测 (v2.6)
  - 硬阴影检测 (v2.6)

设计原则: 宁可多报警少漏报. 操作员重拍一次只需 5 秒,
但一个错误的对色判定可能导致整批返工.
"""

from __future__ import annotations
from typing import Any
import cv2
import numpy as np


def _auto_orient(image_bgr: np.ndarray) -> np.ndarray:
    """Auto-rotate based on EXIF orientation if present.

    OpenCV's imread does not honour EXIF orientation tags.  We apply two
    heuristics in order:

    1. Try to read the raw EXIF orientation byte from the JPEG header
       (lightweight, no extra dependency).
    2. Fallback: if the image is portrait-like (height > 1.5 * width) it was
       likely shot on a phone held vertically — rotate 90 degrees CCW so that
       subsequent analysis sees the expected landscape layout.
    """
    # --- Attempt 1: lightweight EXIF orientation parse (JPEG only) ---
    try:
        # Re-encode to buffer so we can inspect the raw bytes for the
        # orientation tag without pulling in a heavy EXIF library.
        ok, buf = cv2.imencode(".jpg", image_bgr)
        if ok:
            data = bytes(buf)
            # JPEG APP1 EXIF orientation tag id = 0x0112
            idx = data.find(b"\x01\x12")
            if idx != -1 and idx + 4 < len(data):
                orient = data[idx + 2] * 256 + data[idx + 3]
                if orient == 0:
                    orient = data[idx + 3]
                if orient == 3:
                    image_bgr = cv2.rotate(image_bgr, cv2.ROTATE_180)
                    return image_bgr
                elif orient == 6:
                    image_bgr = cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE)
                    return image_bgr
                elif orient == 8:
                    image_bgr = cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    return image_bgr
    except Exception:  # noqa: BLE001
        pass  # EXIF parse failed — fall through to heuristic

    # --- Attempt 2: aspect-ratio heuristic for portrait phone photos ---
    h, w = image_bgr.shape[:2]
    if h > w * 1.5:
        # Likely a portrait phone photo that should be landscape — rotate 90 CCW
        image_bgr = cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image_bgr


def detect_outdoor_environment(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测是否为户外拍摄环境.

    分析维度:
      1. 色温估算 (R/B比值) — 户外日光偏蓝/中性, 室内钨丝灯偏暖
      2. 天空区域检测 — 图像上部是否有高亮度+蓝色区域
      3. 硬阴影检测 — 自然光产生的锐利明暗分界
      4. 动态范围 — 户外通常比室内灯箱动态范围更大
      5. 背景纹理 — 水泥/沥青地面的规则纹理模式

    返回:
      environment_type: "outdoor" | "indoor" | "mixed"
      confidence: 0.0-1.0
      details: 各项检测得分与阈值
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    outdoor_score = 0.0
    details: dict[str, Any] = {}

    # ── 1. 色温估算 (基于 R/B 通道比值) ──
    b_mean = float(image_bgr[..., 0].astype(np.float64).mean())
    r_mean = float(image_bgr[..., 2].astype(np.float64).mean())
    rb_ratio = r_mean / max(b_mean, 1e-6)
    # 日光 D65 约 rb_ratio ~0.95-1.10; 钨丝灯 ~1.3-1.8; LED ~1.0-1.15
    # 户外阴天偏蓝 ~0.85-0.95
    estimated_cct = 6500.0  # 默认 D65
    if rb_ratio > 0.01:
        # 简化色温估算: McCamy 近似的简化版
        estimated_cct = 6500.0 / rb_ratio
    details["estimated_cct"] = round(estimated_cct, 0)
    details["rb_ratio"] = round(rb_ratio, 3)
    if estimated_cct > 5000:
        outdoor_score += 0.20  # 偏日光色温

    # ── 2. 天空区域检测 ──
    top_strip = image_bgr[:h // 5, :]
    top_gray = gray[:h // 5, :]
    top_brightness = float(top_gray.mean())
    top_b = float(top_strip[..., 0].astype(np.float64).mean())
    top_r = float(top_strip[..., 2].astype(np.float64).mean())
    sky_like = top_brightness > 160 and top_b > top_r + 5
    details["sky_detected"] = sky_like
    details["top_brightness"] = round(top_brightness, 1)
    if sky_like:
        outdoor_score += 0.25

    # ── 3. 硬阴影检测 ──
    # 硬阴影特征: 亮度梯度突变 (高梯度幅值) 且方向一致
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=5)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)
    grad_mag = np.sqrt(sobel_x ** 2 + sobel_y ** 2)
    # 硬阴影的梯度幅值通常远大于纹理梯度
    high_grad_threshold = float(np.percentile(grad_mag, 95))
    hard_shadow_pixels = grad_mag > high_grad_threshold * 0.8
    # 检测高梯度像素的方向一致性 (硬阴影方向统一)
    grad_angle = np.arctan2(sobel_y, sobel_x + 1e-6)
    high_grad_angles = grad_angle[hard_shadow_pixels]
    if len(high_grad_angles) > 100:
        # 方向直方图集中度: 用圆形方差衡量
        sin_sum = float(np.sin(2 * high_grad_angles).mean())
        cos_sum = float(np.cos(2 * high_grad_angles).mean())
        direction_consistency = float(np.sqrt(sin_sum ** 2 + cos_sum ** 2))
        hard_shadow_ratio = float(hard_shadow_pixels.sum()) / max(hard_shadow_pixels.size, 1)
    else:
        direction_consistency = 0.0
        hard_shadow_ratio = 0.0
    details["hard_shadow_ratio"] = round(hard_shadow_ratio, 4)
    details["shadow_direction_consistency"] = round(direction_consistency, 3)
    has_hard_shadows = direction_consistency > 0.3 and hard_shadow_ratio > 0.03
    details["hard_shadows_detected"] = has_hard_shadows
    if has_hard_shadows:
        outdoor_score += 0.25

    # ── 4. 动态范围评估 ──
    p5 = float(np.percentile(gray, 5))
    p95 = float(np.percentile(gray, 95))
    dynamic_range = p95 - p5
    details["dynamic_range"] = round(dynamic_range, 1)
    details["brightness_p5"] = round(p5, 1)
    details["brightness_p95"] = round(p95, 1)
    if dynamic_range > 150:
        outdoor_score += 0.15
    elif dynamic_range > 120:
        outdoor_score += 0.08

    # ── 5. 背景纹理检测 (水泥/沥青地面) ──
    # 分析图像四边各 10% 区域的纹理规律性
    border_h = max(20, h // 10)
    border_w = max(20, w // 10)
    border_regions = [
        gray[:border_h, :],           # 上
        gray[-border_h:, :],          # 下
        gray[:, :border_w],            # 左
        gray[:, -border_w:],           # 右
    ]
    texture_scores = []
    for region in border_regions:
        if region.size < 400:
            continue
        lap_var = float(cv2.Laplacian(region, cv2.CV_32F).var())
        texture_scores.append(lap_var)
    avg_border_texture = float(np.mean(texture_scores)) if texture_scores else 0.0
    details["border_texture_score"] = round(avg_border_texture, 1)
    # 水泥地面有中等纹理 (比光滑桌面高, 比木纹板低)
    if 50 < avg_border_texture < 800:
        outdoor_score += 0.15

    # ── 综合判定 ──
    outdoor_score = min(outdoor_score, 1.0)
    if outdoor_score >= 0.45:
        env_type = "outdoor"
    elif outdoor_score >= 0.25:
        env_type = "mixed"
    else:
        env_type = "indoor"

    details["outdoor_score"] = round(outdoor_score, 3)

    return {
        "environment_type": env_type,
        "confidence": round(outdoor_score, 3),
        "estimated_cct": details["estimated_cct"],
        "hard_shadows_detected": has_hard_shadows,
        "sky_detected": sky_like,
        "dynamic_range": dynamic_range,
        "details": details,
    }


def preflight_check(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    图像质量预检. 在 analyze_photo 之前调用.

    返回:
      ok: bool — 是否可以继续分析
      warnings: list — 警告列表 (可以继续但需注意)
      errors: list — 错误列表 (建议重拍)
      scores: dict — 各项质量评分
    """
    # ── Auto-orient: fix EXIF rotation before any analysis ──
    image_bgr = _auto_orient(image_bgr)

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    errors: list[str] = []
    warnings: list[str] = []
    scores: dict[str, float] = {}
    retake_guidance: list[dict[str, Any]] = []

    # ── 1. 模糊检测 (噪声感知 Laplacian 方差) ──
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(lap.var())
    # 噪声估计: 高频噪声会抬高Laplacian方差，需要补偿
    noise_est = float(np.median(np.abs(lap))) * 1.4826  # MAD-based noise
    adjusted_sharpness = blur_score / max(1.0 + noise_est * 0.1, 1.0)
    scores["sharpness"] = round(blur_score, 1)
    scores["noise_estimate"] = round(noise_est, 1)
    scores["adjusted_sharpness"] = round(adjusted_sharpness, 1)
    if adjusted_sharpness < 30:
        errors.append("照片严重模糊，请稳住手机重新拍摄")
        retake_guidance.append({
            "issue": "blur",
            "action": "固定手机在三脚架或平面上，使用定时快门避免抖动",
            "auto_recoverable": False,
        })
    elif adjusted_sharpness < 80:
        warnings.append("照片轻微模糊，可能影响精度")
        retake_guidance.append({
            "issue": "slight_blur",
            "action": "尝试稳住手机或使用连拍模式选最清晰的一张",
            "auto_recoverable": True,
        })
    if noise_est > 50:
        warnings.append(f"检测到较高图像噪声 (噪声指数={noise_est:.0f})，建议在更好光线下拍摄")

    # ── 2. 亮度检测 ──
    mean_brightness = float(gray.mean())
    scores["brightness"] = round(mean_brightness, 1)
    if mean_brightness < 40:
        errors.append("照片太暗，请在光线充足的地方拍摄 (当前亮度={:.0f}, 需要>60)".format(mean_brightness))
        retake_guidance.append({
            "issue": "too_dark",
            "action": "打开灯箱或移到光线充足的位置，确保亮度>60",
            "auto_recoverable": False,
        })
    elif mean_brightness < 60:
        warnings.append("照片偏暗，建议打开灯光 (亮度={:.0f})".format(mean_brightness))
        retake_guidance.append({
            "issue": "dim",
            "action": "增加环境光或调高灯箱亮度",
            "auto_recoverable": True,
        })
    elif mean_brightness > 220:
        warnings.append("照片过亮，请避免强光直射 (亮度={:.0f})".format(mean_brightness))
        retake_guidance.append({
            "issue": "overexposure",
            "action": "减少光源强度或调低手机曝光补偿",
            "auto_recoverable": True,
        })

    # ── 3. 过曝检测 (像素饱和) ──
    overexposed_ratio = float(np.mean(gray > 250))
    scores["overexposed_ratio"] = round(overexposed_ratio, 4)
    if overexposed_ratio > 0.40:
        errors.append("严重过曝 ({:.0f}%)，可能是闪光灯或纯白图片，请重拍".format(overexposed_ratio * 100))
        retake_guidance.append({
            "issue": "severe_overexposure",
            "action": "关闭闪光灯，降低曝光补偿，避免强光直射产品表面",
            "auto_recoverable": False,
        })
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

    # ── 5.5 户外环境检测 ──
    env_info = detect_outdoor_environment(image_bgr)
    scores["outdoor_score"] = env_info["confidence"]
    is_outdoor = env_info["environment_type"] == "outdoor"

    if is_outdoor:
        warnings.append("检测到户外拍摄环境 (置信度={:.0f}%)，已自动切换户外模式".format(env_info["confidence"] * 100))
        if env_info["hard_shadows_detected"]:
            warnings.append("检测到硬阴影，建议移到阴凉处或用遮阳板避免阴影投射到板面")
        if env_info.get("estimated_cct", 6500) > 7500:
            warnings.append("色温偏高 (阴天/蓝天)，色彩可能偏蓝，建议使用灰卡辅助校准")

    # ── 6. 光照均匀性 ──
    # 四个象限亮度比较
    q1 = float(gray[:h//2, :w//2].mean())
    q2 = float(gray[:h//2, w//2:].mean())
    q3 = float(gray[h//2:, :w//2].mean())
    q4 = float(gray[h//2:, w//2:].mean())
    light_range = max(q1, q2, q3, q4) - min(q1, q2, q3, q4)
    scores["lighting_uniformity"] = round(light_range, 1)
    # 户外模式放宽光照均匀性阈值 (40 → 60)
    uniformity_threshold = 60 if is_outdoor else 40
    if light_range > uniformity_threshold:
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

    # ── 10. 截图检测 (手机截图而非相机拍照) ──
    # 截图特征: 顶部状态栏(高亮+文字)、底部导航栏(均匀色块)、精确16:9或类似比例
    top_20 = gray[:max(20, h // 25), :]
    bot_20 = gray[-max(20, h // 25):, :]
    top_var = float(top_20.var()) if top_20.size > 0 else 999
    bot_var = float(bot_20.var()) if bot_20.size > 0 else 999
    top_mean_b = float(top_20.mean()) if top_20.size > 0 else 128
    # 截图状态栏通常很暗或很亮且方差低
    screenshot_score = 0
    if top_var < 300 and (top_mean_b > 200 or top_mean_b < 40):
        screenshot_score += 1
    if bot_var < 200:
        screenshot_score += 1
    aspect = w / max(h, 1)
    if abs(aspect - 9/16) < 0.02 or abs(aspect - 9/19.5) < 0.02:
        screenshot_score += 1
    if screenshot_score >= 2:
        warnings.append("疑似手机截图而非相机拍照 — 请使用相机直接拍摄产品")
    scores["screenshot_score"] = screenshot_score

    # ── 11. 饱和度检测 (低=灰卡误放, 高=手机HDR过处理) ──
    saturation = hsv[..., 1]
    mean_sat = float(saturation.mean())
    scores["saturation"] = round(mean_sat, 1)
    over_sat_pct = float(np.mean(saturation > 240)) * 100
    scores["over_saturation_pct"] = round(over_sat_pct, 1)
    if over_sat_pct > 15:
        warnings.append(f"检测到过饱和像素 ({over_sat_pct:.1f}%)，可能是手机HDR/AI增强导致色彩失真，建议关闭自动增强")
    elif over_sat_pct > 8:
        warnings.append(f"部分过饱和 ({over_sat_pct:.1f}%)，色彩可能被手机处理过")

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
        "environment": env_info,
        "retake_guidance": retake_guidance,
        "corrected_image": image_bgr,  # auto-oriented image for downstream use
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
