"""
SENIA 自动对色模块 — 不靠人对色的完整方案
==========================================

解决真实产线场景的 7 大问题:
  1. 光源不可控 → 色卡校正 + 灰世界白平衡双保险
  2. 无色彩参考 → 强制色卡流程 + 无色卡降级模式
  3. 标样在大货上 → 自动分割两个矩形区域
  4. 背景干扰   → 基于面积比和颜色的智能分割
  5. 手写/贴纸  → 异常像素遮罩
  6. 透视畸变   → 四点透视校正
  7. 木纹定位   → 纹理抑制后取底色, 不依赖花纹配准

核心设计原则:
  - 不要求找到"同一位置的花纹"
  - 对的是"底色 + 整体色调", 不是纹理细节
  - 木纹膜的关键: 底色一致 + 纹理深浅一致 = 视觉一致
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from senia_calibration import ciede2000, srgb_to_lab_d50


# ══════════════════════════════════════════════════════════
# 1. 拍摄工位验证 — 在软件层面卡住不合规的图片
# ══════════════════════════════════════════════════════════

@dataclass
class CaptureValidation:
    """拍摄质量验证结果, 不合格则拒绝分析."""
    is_valid: bool = True
    score: float = 1.0
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def validate_capture_conditions(
    image_brightness: float,
    image_contrast: float,
    has_colorchecker: bool = False,
    has_aruco: bool = False,
    board_detected: bool = False,
    sample_detected: bool = False,
    board_tilt_deg: float = 0.0,
    lighting_uniformity: float = 1.0,
) -> CaptureValidation:
    """
    验证拍摄条件是否满足自动对色要求.
    如果不满足, 拒绝分析并告诉操作员怎么修.
    """
    v = CaptureValidation()

    # 亮度检查
    if image_brightness < 60:
        v.issues.append("图像过暗 (亮度={:.0f}), 请增加光源或调整曝光".format(image_brightness))
        v.score -= 0.3
    elif image_brightness > 220:
        v.issues.append("图像过曝 (亮度={:.0f}), 请降低曝光".format(image_brightness))
        v.score -= 0.3

    # 对比度检查
    if image_contrast < 20:
        v.issues.append("对比度过低, 可能镜头脏或严重跑焦")
        v.score -= 0.2

    # 大货/标样检测
    if not board_detected:
        v.issues.append("未检测到大货区域, 请确保整版膜在画面中居中")
        v.score -= 0.4
    if not sample_detected:
        v.issues.append("未检测到标样区域, 请将标样放在大货右上角")
        v.score -= 0.4

    # 倾斜检查
    if board_tilt_deg > 15:
        v.issues.append(f"大货倾斜 {board_tilt_deg:.1f}°, 请尽量正对拍摄")
        v.score -= 0.15

    # 光照均匀性
    if lighting_uniformity < 0.7:
        v.warnings.append("光照不均匀, 可能影响色差判断")
        v.score -= 0.1

    # 色卡
    if not has_colorchecker:
        v.warnings.append("未检测到色卡, 将使用灰世界白平衡 (精度降低)")
        v.score -= 0.05

    # ArUco
    if not has_aruco:
        v.warnings.append("未检测到定位标记, 使用轮廓检测 (精度略低)")

    # 总评
    v.score = max(0.0, min(1.0, v.score))
    if v.score < 0.5:
        v.is_valid = False
        v.suggestions.append("拍摄条件不满足自动对色要求, 请按以下步骤修正后重拍")
    elif v.score < 0.8:
        v.suggestions.append("拍摄条件勉强可用, 结果仅供参考")

    # 通用建议
    if not has_colorchecker:
        v.suggestions.append("建议: 在大货旁放置 X-Rite ColorChecker 色卡, 显著提升准确度")
    if board_tilt_deg > 5:
        v.suggestions.append("建议: 使用翻拍架从正上方拍摄, 消除透视畸变")

    return v


# ══════════════════════════════════════════════════════════
# 2. 纹理抑制 — 木纹膜的核心: 对底色不对纹理
# ══════════════════════════════════════════════════════════

def texture_suppress_lab(
    lab_values: list[tuple[float, float, float]],
    percentile_low: float = 15.0,
    percentile_high: float = 85.0,
) -> tuple[float, float, float]:
    """
    从木纹膜的多个采样点中提取"底色".

    原理: 木纹 = 底色 + 深色纹理线条
    深色线条拉低 L 值, 所以取 L 通道的中高百分位就是底色.
    a/b 通道用鲁棒均值 (截尾均值) 避免极端值干扰.
    """
    if not lab_values:
        return (50.0, 0.0, 0.0)

    L_vals = sorted(v[0] for v in lab_values)
    a_vals = sorted(v[1] for v in lab_values)
    b_vals = sorted(v[2] for v in lab_values)

    n = len(L_vals)
    lo = max(0, int(n * percentile_low / 100))
    hi = min(n - 1, int(n * percentile_high / 100))

    # L 通道: 取高百分位区间均值 (底色, 排除纹理线条)
    L_base = statistics.mean(L_vals[hi - max(1, (hi - lo) // 2):hi + 1]) if hi > lo else statistics.mean(L_vals)

    # a/b 通道: 截尾均值
    trim = max(1, n // 10)
    a_trim = statistics.mean(a_vals[trim:n - trim]) if n > 2 * trim else statistics.mean(a_vals)
    b_trim = statistics.mean(b_vals[trim:n - trim]) if n > 2 * trim else statistics.mean(b_vals)

    return (round(L_base, 4), round(a_trim, 4), round(b_trim, 4))


def extract_grain_depth(lab_values: list[tuple[float, float, float]]) -> float:
    """
    提取木纹深浅度: 底色L - 纹理L.
    这是木纹膜的第二个关键指标: 纹理深浅一致才视觉一致.
    """
    if len(lab_values) < 4:
        return 0.0
    L_vals = sorted(v[0] for v in lab_values)
    n = len(L_vals)
    # 底色 = 亮区均值 (top 20%), 纹理 = 暗区均值 (bottom 20%)
    top_n = max(1, n // 5)
    base_L = statistics.mean(L_vals[-top_n:])
    grain_L = statistics.mean(L_vals[:top_n])
    return round(base_L - grain_L, 2)


# ══════════════════════════════════════════════════════════
# 3. 灰世界白平衡 (无色卡降级模式)
# ══════════════════════════════════════════════════════════

def gray_world_correction(
    rgb_values: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """
    灰世界假设: 场景平均色应该是中性灰.
    计算全图 RGB 均值, 缩放到灰色中心.
    """
    if not rgb_values:
        return rgb_values
    n = len(rgb_values)
    r_avg = sum(v[0] for v in rgb_values) / n
    g_avg = sum(v[1] for v in rgb_values) / n
    b_avg = sum(v[2] for v in rgb_values) / n
    gray = (r_avg + g_avg + b_avg) / 3.0

    if r_avg < 1:
        r_avg = 1
    if g_avg < 1:
        g_avg = 1
    if b_avg < 1:
        b_avg = 1

    r_scale = gray / r_avg
    g_scale = gray / g_avg
    b_scale = gray / b_avg

    corrected = []
    for r, g, b in rgb_values:
        corrected.append((
            max(0, min(255, int(r * r_scale + 0.5))),
            max(0, min(255, int(g * g_scale + 0.5))),
            max(0, min(255, int(b * b_scale + 0.5))),
        ))
    return corrected


# ══════════════════════════════════════════════════════════
# 4. 异常像素过滤 — 去除手写、贴纸、反光
# ══════════════════════════════════════════════════════════

def filter_abnormal_pixels(
    lab_values: list[tuple[float, float, float]],
    sigma_multiplier: float = 2.0,
) -> list[tuple[float, float, float]]:
    """
    过滤掉异常像素 (手写墨迹=极暗, 白色贴纸=极亮, 反光=极亮+低饱和).
    用 σ 法则剔除离群值.
    """
    if len(lab_values) < 10:
        return lab_values

    L_vals = [v[0] for v in lab_values]
    L_mean = statistics.mean(L_vals)
    L_std = statistics.stdev(L_vals) if len(L_vals) > 1 else 0

    # 太暗(手写) 或太亮(贴纸/反光) 的剔除
    L_lo = L_mean - sigma_multiplier * max(L_std, 3.0)
    L_hi = L_mean + sigma_multiplier * max(L_std, 3.0)

    # 高饱和度异常 (彩色贴纸等)
    C_vals = [math.hypot(v[1], v[2]) for v in lab_values]
    C_mean = statistics.mean(C_vals)
    C_std = statistics.stdev(C_vals) if len(C_vals) > 1 else 0
    C_hi = C_mean + sigma_multiplier * max(C_std, 3.0)

    filtered = []
    for v in lab_values:
        L, a, b = v
        C = math.hypot(a, b)
        if L_lo <= L <= L_hi and C <= C_hi:
            filtered.append(v)

    # 至少保留 50% 的样本
    if len(filtered) < len(lab_values) * 0.5:
        return lab_values
    return filtered


# ══════════════════════════════════════════════════════════
# 5. 完整自动对色流程 — 不靠人
# ══════════════════════════════════════════════════════════

@dataclass
class AutoMatchResult:
    """自动对色结果."""
    # 判定
    tier: str = ""               # "PASS" / "MARGINAL" / "FAIL"
    dE00: float = 0.0           # 底色 CIEDE2000

    # 底色
    ref_base_lab: tuple[float, float, float] = (0.0, 0.0, 0.0)
    sample_base_lab: tuple[float, float, float] = (0.0, 0.0, 0.0)

    # 偏差方向 (给操作员看的)
    directions: list[str] = field(default_factory=list)
    direction_summary: str = ""  # "偏红偏亮" 一句话

    # 纹理深浅对比
    ref_grain_depth: float = 0.0
    sample_grain_depth: float = 0.0
    grain_depth_diff: float = 0.0
    grain_match: str = ""        # "一致" / "标样纹理更深" / "大货纹理更深"

    # 调色建议
    recipe_advices: list[str] = field(default_factory=list)
    root_cause: str = ""         # "recipe" / "process" / "ok"

    # 拍摄质量
    capture_quality: float = 1.0
    capture_warnings: list[str] = field(default_factory=list)

    # 详细数据 (给技术人员看的)
    details: dict[str, Any] = field(default_factory=dict)


def auto_match(
    ref_rgb_samples: list[tuple[int, int, int]],
    board_rgb_samples: list[tuple[int, int, int]],
    profile: str = "wood",
    apply_white_balance: bool = True,
    capture_quality: float = 1.0,
) -> AutoMatchResult:
    """
    全自动对色入口.

    参数:
      ref_rgb_samples: 标样区域的 RGB 采样点 (已裁切, 尽量密集)
      board_rgb_samples: 大货区域的 RGB 采样点 (已裁切)
      profile: "wood" / "solid" / "stone" / "metallic" / "high_gloss"
      apply_white_balance: 是否做灰世界白平衡 (无色卡时启用)
      capture_quality: 拍摄质量分 (0~1, 来自 validate_capture_conditions)

    返回 AutoMatchResult 含判定、偏差方向、调色建议.
    """
    result = AutoMatchResult(capture_quality=capture_quality)

    # Step 1: 白平衡 (无色卡降级模式)
    if apply_white_balance:
        all_pixels = ref_rgb_samples + board_rgb_samples
        ref_wb = gray_world_correction(ref_rgb_samples)
        board_wb = gray_world_correction(board_rgb_samples)
    else:
        ref_wb = ref_rgb_samples
        board_wb = board_rgb_samples

    # Step 2: RGB → Lab
    ref_labs = [srgb_to_lab_d50(r, g, b) for r, g, b in ref_wb]
    board_labs = [srgb_to_lab_d50(r, g, b) for r, g, b in board_wb]

    # Step 3: 过滤异常像素 (手写/贴纸/反光)
    ref_labs_clean = filter_abnormal_pixels(ref_labs)
    board_labs_clean = filter_abnormal_pixels(board_labs)

    # Step 4: 提取底色 (纹理抑制)
    if profile in ("wood", "stone"):
        ref_base = texture_suppress_lab(ref_labs_clean)
        board_base = texture_suppress_lab(board_labs_clean)
    else:
        # 纯色膜直接取均值
        ref_base = _mean_lab(ref_labs_clean)
        board_base = _mean_lab(board_labs_clean)

    result.ref_base_lab = ref_base
    result.sample_base_lab = board_base

    # Step 5: 计算底色色差
    de = ciede2000(ref_base[0], ref_base[1], ref_base[2],
                   board_base[0], board_base[1], board_base[2])
    result.dE00 = de["dE00"]
    da = board_base[1] - ref_base[1]
    db = board_base[2] - ref_base[2]

    # Step 6: 偏差方向
    dirs = []
    if abs(de["dL"]) > 0.5:
        dirs.append("偏亮" if de["dL"] > 0 else "偏暗")
    if abs(da) > 0.5:
        dirs.append("偏红" if da > 0 else "偏绿")
    if abs(db) > 0.5:
        dirs.append("偏黄" if db > 0 else "偏蓝")
    if abs(de["dC"]) > 0.5:
        dirs.append("饱和度偏高" if de["dC"] > 0 else "饱和度不足/偏灰")
    result.directions = dirs
    result.direction_summary = "".join(dirs) if dirs else "色差极小"

    # Step 7: 木纹深浅对比
    if profile in ("wood", "stone"):
        result.ref_grain_depth = extract_grain_depth(ref_labs_clean)
        result.sample_grain_depth = extract_grain_depth(board_labs_clean)
        result.grain_depth_diff = round(result.sample_grain_depth - result.ref_grain_depth, 2)
        if abs(result.grain_depth_diff) < 1.5:
            result.grain_match = "纹理深浅一致"
        elif result.grain_depth_diff > 0:
            result.grain_match = "大货纹理比标样更深"
        else:
            result.grain_match = "标样纹理比大货更深"

    # Step 8: 三级判定
    thresholds = _get_thresholds(profile)
    if result.dE00 < thresholds["pass"]:
        result.tier = "PASS"
    elif result.dE00 < thresholds["marginal"]:
        result.tier = "MARGINAL"
    else:
        result.tier = "FAIL"

    # Step 9: 调色建议
    result.recipe_advices, result.root_cause = _generate_simple_advice(
        de["dL"], da, db, de["dC"], result.tier)

    # Step 10: 详细数据
    result.details = {
        "dE00": de["dE00"],
        "dL": de["dL"], "dC": de["dC"], "dH": de["dH"],
        "da": round(da, 4), "db": round(db, 4),
        "ref_base_L": ref_base[0], "ref_base_a": ref_base[1], "ref_base_b": ref_base[2],
        "sample_base_L": board_base[0], "sample_base_a": board_base[1], "sample_base_b": board_base[2],
        "ref_samples_count": len(ref_labs_clean),
        "board_samples_count": len(board_labs_clean),
        "ref_filtered_ratio": round(len(ref_labs_clean) / max(len(ref_labs), 1), 3),
        "board_filtered_ratio": round(len(board_labs_clean) / max(len(board_labs), 1), 3),
        "grain_depth_ref": result.ref_grain_depth,
        "grain_depth_board": result.sample_grain_depth,
        "profile": profile,
    }

    return result


# ── 内部工具 ────────────────────────────────────────────────

def _mean_lab(labs: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not labs:
        return (50.0, 0.0, 0.0)
    n = len(labs)
    return (
        round(sum(v[0] for v in labs) / n, 4),
        round(sum(v[1] for v in labs) / n, 4),
        round(sum(v[2] for v in labs) / n, 4),
    )


def _get_thresholds(profile: str) -> dict[str, float]:
    return {
        "wood":       {"pass": 1.2, "marginal": 2.8},
        "stone":      {"pass": 1.5, "marginal": 3.2},
        "solid":      {"pass": 0.8, "marginal": 2.0},
        "metallic":   {"pass": 0.8, "marginal": 2.2},
        "high_gloss": {"pass": 0.6, "marginal": 1.8},
    }.get(profile, {"pass": 1.0, "marginal": 2.5})


def _generate_simple_advice(
    dL: float, da: float, db: float, dC: float, tier: str,
) -> tuple[list[str], str]:
    """生成简明调色建议 (操作员能看懂的)."""
    if tier == "PASS":
        return ["色差合格, 无需调整"], "ok"

    advices = []
    # 明度
    if dL > 1.0:
        advices.append("→ 偏亮: 减少白色基料/钛白粉")
    elif dL < -1.0:
        advices.append("→ 偏暗: 增加白色基料 或 减少黑色色精")

    # 红绿
    if da > 0.8:
        advices.append("→ 偏红: 减少红色色精")
    elif da < -0.8:
        advices.append("→ 偏绿: 增加红色色精 或 减少绿色色精")

    # 黄蓝
    if db > 0.8:
        advices.append("→ 偏黄: 减少黄色色精")
    elif db < -0.8:
        advices.append("→ 偏蓝: 减少蓝色色精 或 增加黄色色精")

    # 饱和度
    if dC < -1.0:
        advices.append("→ 饱和度不足/偏灰: 增加主色色精浓度")
    elif dC > 1.0:
        advices.append("→ 饱和度过高: 减少主色色精浓度")

    # 复合建议
    if dL > 0.8 and db > 0.8:
        advices.insert(0, "★ 优先减白, 黄色可能随之回正")

    if not advices:
        advices.append("色差在临界范围, 建议人工复核")

    return advices, "recipe"


# ══════════════════════════════════════════════════════════
# 6. 拍摄工位硬件规格 (软件中的常量, 用于文档+校验)
# ══════════════════════════════════════════════════════════

CAPTURE_STATION_SPEC = {
    "title": "SENIA 标准对色拍摄工位规格",
    "light_source": {
        "type": "D65 LED灯箱",
        "CRI": "≥ 95 (Ra95+)",
        "color_temp": "6500K ± 200K",
        "uniformity": "≥ 90% (中心 vs 边缘)",
        "geometry": "45°/0° (光源45°入射, 相机0°正上方)",
        "note": "禁止使用普通日光灯, 荧光灯, 或自然光",
    },
    "camera": {
        "device": "iPhone 12 Pro 或更高型号",
        "format": "ProRAW (DNG)",
        "white_balance": "锁定 (手动设为6500K)",
        "exposure": "锁定 (AE Lock)",
        "focus": "锁定 (AF Lock)",
        "flash": "关闭",
        "HDR": "关闭 (Smart HDR / Deep Fusion 都关)",
        "distance": "40cm ± 5cm (保证分辨率 > 0.1mm/pixel)",
    },
    "fixture": {
        "background": "N7 中性灰背景板 (Munsell N7, L*≈70)",
        "positioning": [
            "大货平铺在拍摄台上",
            "标样放在大货右上角, 长边与大货平行",
            "标样与大货之间留 1cm 间隙 (不要重叠!)",
            "或: 标样和大货并排放置, 各占画面一半",
        ],
        "color_checker": "X-Rite ColorChecker Classic, 放在大货左下角",
        "aruco_markers": "可选: 4个 ArUco 标记贴在拍摄台四角, 用于自动定位",
    },
    "禁止事项": [
        "禁止在自然光/窗边拍摄",
        "禁止标样叠放在大货上方 (受光不一致)",
        "禁止手写文字出现在比对区域内",
        "禁止使用手机自带美颜/滤镜/HDR",
    ],
}
