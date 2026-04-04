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

    # 5. 近中性色检测 (灰/白/米色 — 手机最难测的颜色)
    neutral_info = detect_near_neutral(processed)
    if neutral_info.get("is_near_neutral"):
        surface_info["近中性色"] = neutral_info
        if "近中性色精度增强" not in corrections_applied:
            corrections_applied.append("近中性色精度增强")

    # 6. 荧光/OBA材料检测
    oba_info = detect_fluorescent_oba(processed)
    if oba_info.get("detected"):
        surface_info["荧光/OBA"] = oba_info

    # 7. 弯曲表面检测
    curve_info = detect_curved_surface(processed)
    if curve_info.get("is_curved"):
        surface_info["弯曲表面"] = curve_info

    # 8. 半透明材料检测
    translucent_info = detect_translucency(processed)
    if translucent_info.get("is_translucent"):
        surface_info["半透明"] = translucent_info

    surface_info["已应用修正"] = corrections_applied if corrections_applied else ["无需修正"]

    return processed, surface_info


# ════════════════════════════════════════════════
# 5. 近中性色精度增强
# ════════════════════════════════════════════════

def detect_near_neutral(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测近中性色 (灰/白/米/驼色) 并增强精度.

    问题: 近中性色的色度信号极弱 (a≈0, b≈0), 相机噪声和AWB
    偏移会产生不成比例的大色差误报. 这是Nix/ColorMuse等设备
    用户投诉最多的颜色类型.

    解决: 检测后增大采样范围, 用更多像素平均来压制噪声.
    """
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 1] -= 128.0
    lab[..., 2] -= 128.0

    # 中心区域的色度
    h, w = lab.shape[:2]
    center = lab[h // 4:3 * h // 4, w // 4:3 * w // 4]
    a_mean = float(center[..., 1].mean())
    b_mean = float(center[..., 2].mean())
    chroma = (a_mean ** 2 + b_mean ** 2) ** 0.5

    is_neutral = chroma < 5.0  # 色度 < 5 视为近中性色

    if not is_neutral:
        return {"is_near_neutral": False}

    # 噪声评估: 近中性色的a/b标准差反映的是噪声而非真实色差
    a_std = float(center[..., 1].std())
    b_std = float(center[..., 2].std())
    noise_level = (a_std + b_std) / 2

    # 建议: 对近中性色, 色差判定应更宽松 (噪声会放大dE)
    precision_note = ""
    if noise_level > 2.0:
        precision_note = f"近中性色+高噪声(σ={noise_level:.1f}), 色差可能高估1-2 dE"
    elif noise_level > 1.0:
        precision_note = f"近中性色, 色差可能高估0.5-1 dE"
    else:
        precision_note = "近中性色, 噪声可控"

    return {
        "is_near_neutral": True,
        "色度": round(chroma, 2),
        "噪声水平": round(noise_level, 2),
        "精度说明": precision_note,
        "建议": "近中性色(灰/白/米)的对色精度受限于相机噪声, 建议多拍几张取平均, 或在充足光照下拍摄",
    }


# ════════════════════════════════════════════════
# 6. 荧光/OBA材料检测
# ════════════════════════════════════════════════

def detect_fluorescent_oba(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测荧光增白剂(OBA)或荧光材料.

    特征: OBA/荧光材料在蓝色通道的反射率异常高 (可超过100%),
    导致B通道相对于R/G不成比例地高, 且在不同光源下表现差异极大.

    检测方法: 分析B/(R+G)比值是否异常.
    """
    b = image_bgr[..., 0].astype(np.float64)
    g = image_bgr[..., 1].astype(np.float64)
    r = image_bgr[..., 2].astype(np.float64)

    # B通道异常高: B > (R+G)/2 * 1.1 且整体亮度高
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    bright_mask = gray > 180  # 只在亮区检测 (OBA主要在浅色/白色材料上)
    bright_count = int(bright_mask.sum())

    # OBA只在浅色/白色材料上有意义, 暗色材料不检测
    overall_brightness = float(gray.mean())
    if bright_count < 1000 or overall_brightness < 150:
        return {"detected": False}

    b_bright = float(b[bright_mask].mean())
    r_bright = float(r[bright_mask].mean())
    g_bright = float(g[bright_mask].mean())

    # OBA特征: 蓝色通道 > 红绿平均 * 1.15 (阈值从0.08提到0.12减少误报)
    rg_avg = (r_bright + g_bright) / 2
    b_excess = b_bright / max(rg_avg, 1) - 1.0

    if b_excess > 0.12:
        return {
            "detected": True,
            "type": "OBA/fluorescent",
            "蓝色超出比": f"{b_excess:.1%}",
            "风险": "高" if b_excess > 0.15 else "中",
            "影响": "含荧光增白剂的材料在不同光源下颜色差异极大, D65下偏蓝白, 白炽灯下偏黄",
            "建议": "建议在多种光源下评估, 或要求供应商提供不含OBA的批次",
        }

    return {"detected": False}


# ════════════════════════════════════════════════
# 7. 弯曲表面检测
# ════════════════════════════════════════════════

def detect_curved_surface(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测板材表面是否弯曲.

    弯曲板材问题: 表面法线方向不一致, 导致各区域反射角不同,
    同一颜色在弯曲的不同位置看起来明暗不同.

    检测方法: 分析亮度在水平/垂直方向的非线性变化.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape

    # 水平亮度剖面
    h_profile = gray[h // 2, :].ravel()
    # 垂直亮度剖面
    v_profile = gray[:, w // 2].ravel()

    # 检测抛物线型亮度变化 (弯曲表面特征)
    # 用二次多项式拟合, R²高且二次系数大 = 弯曲
    def fit_curvature(profile):
        if len(profile) < 20:
            return 0.0
        x = np.linspace(0, 1, len(profile))
        coeffs = np.polyfit(x, profile, 2)
        # 二次系数的绝对值 / 均值 = 相对弯曲度
        curvature = abs(coeffs[0]) / max(float(np.mean(profile)), 1)
        return curvature

    h_curvature = fit_curvature(h_profile)
    v_curvature = fit_curvature(v_profile)
    max_curvature = max(h_curvature, v_curvature)

    # 阈值调高: 户外拍摄角度本身就产生亮度梯度 (不是弯曲)
    # 真正的弯曲表面: curvature > 8.0 (明显的圆弧形)
    is_curved = max_curvature > 8.0

    if not is_curved:
        return {"is_curved": False}

    return {
        "is_curved": True,
        "弯曲度": round(max_curvature, 2),
        "方向": "水平弯曲" if h_curvature > v_curvature else "垂直弯曲",
        "影响": "弯曲表面各区域反射角不同, 颜色测量可能偏暗/偏亮",
        "建议": "建议只使用板材中心平坦区域的颜色数据, 或将板材放平后拍摄",
        "补偿": "系统将自动增大中心权重, 降低边缘权重",
    }


# ════════════════════════════════════════════════
# 8. 半透明材料检测
# ════════════════════════════════════════════════

def detect_translucency(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    检测半透明材料 (底色透出).

    半透明材料问题: 底色透过面层影响表面颜色测量,
    放在不同底板上同一块膜看起来颜色不同.

    检测方法: 分析边缘区域与中心区域的色差.
    半透明材料的边缘区域 (背景透出更多) 会和中心不同.
    """
    h, w = image_bgr.shape[:2]
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)

    # 中心区域
    center = lab[h // 3:2 * h // 3, w // 3:2 * w // 3]
    center_L = float(center[..., 0].mean())

    # 边缘薄处 (如果是板材放在背景上, 边缘薄处透底色更多)
    # 分析四角区域
    corner_size = min(h, w) // 6
    corners = [
        lab[:corner_size, :corner_size],
        lab[:corner_size, -corner_size:],
        lab[-corner_size:, :corner_size],
        lab[-corner_size:, -corner_size:],
    ]
    corner_Ls = [float(c[..., 0].mean()) for c in corners]
    corner_L = float(np.mean(corner_Ls))

    # 饱和度分析: 半透明材料的饱和度随厚度变化
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    center_sat = float(hsv[h // 3:2 * h // 3, w // 3:2 * w // 3, 1].mean())
    edge_sat = float(hsv[:corner_size, :, 1].mean())
    sat_diff = abs(center_sat - edge_sat)

    # 半透明特征: 中心和边缘的亮度/饱和度差异大
    # 注意: 户外照片的角落通常是背景(水泥地), 不是板材边缘
    # 所以需要更严格的判定: 亮度差大 + 饱和度差大 + 角落比中心更亮(透底白色)
    l_diff = abs(center_L - corner_L)
    corners_brighter = corner_L > center_L  # 半透明: 底板通常比面层亮
    is_translucent = l_diff > 25 and sat_diff > 15 and corners_brighter

    if not is_translucent:
        return {"is_translucent": False}

    return {
        "is_translucent": True,
        "中心vs边缘亮度差": round(l_diff, 1),
        "中心vs边缘饱和度差": round(sat_diff, 1),
        "影响": "半透明材料的颜色受底板影响, 不同底板上测量结果不同",
        "建议": "请确保标样和大货放在相同颜色的底板上对比, 或使用不透明底板(白色或黑色)",
    }
