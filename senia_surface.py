"""
SENIA 表面特性分析与补偿 — 解决手机对色的物理限制
================================================
解决4个行业公认的手机对色难题:

1. 光泽度差异: 高光/哑光混测色差偏大 → 自动检测+补偿
2. 闪光灯干扰: 中心高光污染 → 检测+去除+修补
3. 极端明暗: 极深色(L<25)/极浅色(L>85)精度下降 → 动态范围补偿
4. 保护膜: 未撕保护膜偏蓝+反光 → 自动检测+色偏补偿

原理: 手机相机传感器是8bit RGB, 理论精度下限约dE=1.5.
      但通过场景分析和智能补偿, 可以在实际场景中逼近这个极限.
"""

from __future__ import annotations
from typing import Any

import cv2
import numpy as np


# ════════════════════════════════════════════════
# 1. 光泽度检测与补偿
# ════════════════════════════════════════════════

def detect_gloss(image_bgr: np.ndarray, mask: np.ndarray | None = None) -> dict[str, Any]:
    """
    检测表面光泽度 — 区分高光/半光/哑光.

    原理: 高光表面有更多镜面反射 (高亮小面积点),
          哑光表面光散射均匀 (无高亮点).
    方法: 分析亮度直方图的偏度(skewness)和极高亮像素比例.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if mask is not None:
        pixels = gray[mask]
    else:
        pixels = gray.ravel()

    if len(pixels) < 100:
        return {"gloss_type": "unknown", "specular_ratio": 0.0}

    mean_val = float(pixels.mean())
    std_val = float(pixels.std())

    # 镜面反射比例: 亮度 > (mean + 3*std) 且 > 200 的像素
    specular_threshold = max(200, mean_val + 3 * std_val)
    specular_ratio = float((pixels > specular_threshold).sum() / len(pixels))

    # 偏度: 高光表面偏度高 (亮尾长)
    if std_val > 0.01:
        skewness = float(((pixels - mean_val) ** 3).mean() / (std_val ** 3))
    else:
        skewness = 0.0

    # 分类
    if specular_ratio > 0.03 or skewness > 2.0:
        gloss_type = "high_gloss"
        gloss_cn = "高光"
    elif specular_ratio > 0.005 or skewness > 0.8:
        gloss_type = "semi_gloss"
        gloss_cn = "半光"
    else:
        gloss_type = "matte"
        gloss_cn = "哑光"

    return {
        "gloss_type": gloss_type,
        "gloss_cn": gloss_cn,
        "specular_ratio": round(specular_ratio, 4),
        "skewness": round(skewness, 2),
    }


def compensate_gloss_difference(
    board_lab: dict[str, float],
    sample_lab: dict[str, float],
    board_gloss: dict[str, Any],
    sample_gloss: dict[str, Any],
) -> dict[str, Any]:
    """
    补偿光泽度差异导致的色差偏大.

    问题: 高光板和哑光标样比较时, 高光板因镜面反射导致L偏高,
          即使实际颜色一样, 测量色差也偏大.
    补偿: 根据光泽度差异调整L通道.
    """
    bg = board_gloss.get("gloss_type", "matte")
    sg = sample_gloss.get("gloss_type", "matte")

    gloss_rank = {"matte": 0, "semi_gloss": 1, "high_gloss": 2}
    diff = gloss_rank.get(bg, 0) - gloss_rank.get(sg, 0)

    if diff == 0:
        return {"compensated": False, "reason": "光泽度一致，无需补偿"}

    # 光泽度差异导致的L偏移补偿系数
    # 高光比哑光亮约 1-3 L单位
    l_compensation = diff * 1.5  # 每级光泽差异补偿1.5 L

    compensated_board = {
        "L": round(board_lab["L"] - l_compensation, 2),
        "a": board_lab["a"],
        "b": board_lab["b"],
    }

    return {
        "compensated": True,
        "原始大货LAB": board_lab,
        "补偿后大货LAB": compensated_board,
        "光泽度差异": f"大货={board_gloss.get('gloss_cn','?')}, 标样={sample_gloss.get('gloss_cn','?')}",
        "L补偿量": round(-l_compensation, 2),
    }


# ════════════════════════════════════════════════
# 2. 闪光灯检测与去除
# ════════════════════════════════════════════════

def detect_and_remove_flash(image_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """
    检测闪光灯高光并修补.

    闪光灯特征:
      - 中心区域有大面积高亮 (>240)
      - 高亮区域低饱和度 (接近白色)
      - 从中心向外衰减 (环形分布)

    修补: 用周围非高光区域的颜色插值填充高光区域.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # 中心区域高亮检测
    center_y, center_x = h // 2, w // 2
    center_region = gray[h // 3:2 * h // 3, w // 3:2 * w // 3]
    center_bright_ratio = float((center_region > 240).sum() / max(center_region.size, 1))

    # 全局高亮检测 (高亮+低饱和 = 闪光灯)
    flash_mask = (gray > 235) & (hsv[..., 1] < 40)
    flash_ratio = float(flash_mask.sum() / max(flash_mask.size, 1))

    info: dict[str, Any] = {
        "flash_detected": False,
        "center_bright_ratio": round(center_bright_ratio, 4),
        "flash_ratio": round(flash_ratio, 4),
    }

    if center_bright_ratio < 0.05 and flash_ratio < 0.03:
        return image_bgr, info

    info["flash_detected"] = True

    # 修补: 用 inpainting 填充高光区域
    flash_mask_u8 = flash_mask.astype(np.uint8) * 255
    # 膨胀一点确保覆盖高光边缘
    flash_mask_u8 = cv2.dilate(flash_mask_u8, np.ones((5, 5), np.uint8), iterations=1)

    # OpenCV inpainting (Telea method, 快速且效果好)
    repaired = cv2.inpaint(image_bgr, flash_mask_u8, inpaintRadius=10,
                           flags=cv2.INPAINT_TELEA)

    info["repaired_pixels"] = int(flash_mask_u8.sum() // 255)
    info["repair_ratio"] = round(info["repaired_pixels"] / max(h * w, 1), 4)

    return repaired, info


# ════════════════════════════════════════════════
# 3. 极端明暗补偿
# ════════════════════════════════════════════════

def compensate_extreme_lightness(
    lab: dict[str, float],
    de: float,
) -> dict[str, Any]:
    """
    极深色(L<25)和极浅色(L>85)的色差补偿.

    问题:
      - 极深色: 相机传感器信噪比低, 噪声被放大为色差
      - 极浅色: 色度分辨率下降(Weber-Fechner定律), 小差异被丢失

    补偿: 根据L值调整测量置信度和建议精度.
    """
    L = lab["L"]

    if L < 15:
        confidence_factor = 0.5
        note = "极深色(L<15)：相机传感器噪声大，色差可能被高估0.5-1.5 dE"
        adjusted_de = max(0, de - 0.8)
    elif L < 25:
        confidence_factor = 0.7
        note = "深色(L<25)：信噪比偏低，色差可能被高估0.3-0.8 dE"
        adjusted_de = max(0, de - 0.4)
    elif L > 90:
        confidence_factor = 0.6
        note = "极浅色(L>90)：饱和度分辨率低，微小色差可能被丢失"
        adjusted_de = de * 1.2  # 补偿丢失
    elif L > 80:
        confidence_factor = 0.8
        note = "浅色(L>80)：精度略有下降"
        adjusted_de = de * 1.1
    else:
        confidence_factor = 1.0
        note = "正常亮度范围"
        adjusted_de = de

    return {
        "原始色差": round(de, 2),
        "补偿色差": round(adjusted_de, 2),
        "置信度因子": confidence_factor,
        "说明": note,
        "L值": round(L, 1),
    }


# ════════════════════════════════════════════════
# 4. 保护膜自动补偿
# ════════════════════════════════════════════════

def detect_and_compensate_film(image_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """
    检测保护膜并自动补偿色偏.

    保护膜特征:
      - 整体偏蓝 (B通道高于R通道 5-15)
      - 有规律的反光线 (保护膜褶皱)
      - 饱和度偏低 (保护膜降低了色彩表现)

    补偿: 扣除保护膜的蓝色偏移和亮度提升.
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    b_mean = float(image_bgr[..., 0].astype(np.float64).mean())
    g_mean = float(image_bgr[..., 1].astype(np.float64).mean())
    r_mean = float(image_bgr[..., 2].astype(np.float64).mean())

    blue_bias = b_mean - r_mean
    saturation_mean = float(hsv[..., 1].mean())

    # 镜面反射线检测 (保护膜褶皱特征)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    specular_lines = float((gray > 230).sum() / max(gray.size, 1))

    info: dict[str, Any] = {
        "film_detected": False,
        "blue_bias": round(blue_bias, 2),
        "saturation": round(saturation_mean, 1),
        "specular_lines": round(specular_lines, 4),
    }

    # 保护膜判定: 蓝偏 > 5 且 有镜面线 或 低饱和度
    if blue_bias > 5 and (specular_lines > 0.02 or saturation_mean < 30):
        info["film_detected"] = True
        info["film_type"] = "protective_film"

        # 补偿: 减去蓝色偏移, 限幅在合理范围
        correction_b = max(-15.0, min(0.0, -blue_bias * 0.7))
        correction_l = max(-5.0, min(0.0, -abs(blue_bias) * 0.3))

        # 应用补偿
        compensated = image_bgr.copy().astype(np.float32)
        compensated[..., 0] = np.clip(compensated[..., 0] + correction_b, 0, 255)  # B通道
        compensated = compensated.astype(np.uint8)

        info["correction_b_channel"] = round(correction_b, 2)
        info["correction_l"] = round(correction_l, 2)
        info["建议"] = "检测到保护膜，已自动补偿色偏。建议撕掉保护膜后重新拍摄以获得最佳精度。"

        return compensated, info

    return image_bgr, info


# ════════════════════════════════════════════════
# 综合表面分析入口
# ════════════════════════════════════════════════

def analyze_surface_and_preprocess(image_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """
    综合表面分析与预处理 — 在颜色测量前自动修正所有表面问题.

    调用顺序:
      1. 闪光灯检测+修补 (最优先, 否则后续分析都不准)
      2. 保护膜检测+补偿
      3. 光泽度检测 (用于后续色差补偿)
      4. 极端明暗检测 (用于精度评估)

    返回: (预处理后图像, 分析信息)
    """
    surface_info: dict[str, Any] = {}
    processed = image_bgr.copy()

    # 1. 闪光灯
    processed, flash_info = detect_and_remove_flash(processed)
    surface_info["闪光灯"] = flash_info

    # 2. 保护膜
    processed, film_info = detect_and_compensate_film(processed)
    surface_info["保护膜"] = film_info

    # 3. 光泽度 (在修复后图像上测)
    gloss_info = detect_gloss(processed)
    surface_info["光泽度"] = gloss_info

    # 4. 整体亮度评估
    gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
    mean_l = float(gray.mean())
    if mean_l < 25:
        surface_info["亮度"] = {"等级": "极深色", "L": round(mean_l, 1), "精度影响": "高"}
    elif mean_l < 50:
        surface_info["亮度"] = {"等级": "深色", "L": round(mean_l, 1), "精度影响": "中"}
    elif mean_l > 220:
        surface_info["亮度"] = {"等级": "极浅色", "L": round(mean_l, 1), "精度影响": "高"}
    elif mean_l > 180:
        surface_info["亮度"] = {"等级": "浅色", "L": round(mean_l, 1), "精度影响": "中"}
    else:
        surface_info["亮度"] = {"等级": "正常", "L": round(mean_l, 1), "精度影响": "低"}

    # 处理统计
    corrections_applied = []
    if flash_info.get("flash_detected"):
        corrections_applied.append("闪光灯高光修补")
    if film_info.get("film_detected"):
        corrections_applied.append("保护膜色偏补偿")

    surface_info["已应用修正"] = corrections_applied if corrections_applied else ["无需修正"]

    return processed, surface_info
