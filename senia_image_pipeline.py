"""
SENIA 图像全自动对色管线
========================
从一张原始照片到最终判定+调色建议, 全程不需要人.

流程:
  拍照 → 自动检测大货/标样 → 透视校正 → 去手写/贴纸 →
  纹理抑制提取底色 → CIEDE2000色差 → 三级判定 →
  偏差方向+调色建议 → 空间均匀性→根因分析 →
  输出报告(JSON+热图+标注图)

依赖: OpenCV (cv2), numpy
集成: elite_color_match.py 的检测/校正能力 + senia 核心分析模块
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# 复用现有能力
from elite_color_match import (
    PROFILES,
    bgr_to_lab_float,
    build_invalid_mask,
    build_material_mask,
    choose_board_and_sample,
    compute_confidence,
    contour_candidates,
    detect_aruco_board_quad,
    draw_detection_overlay,
    draw_heatmap_on_board,
    infer_profile,
    order_quad,
    warp_quad,
    robust_mean_lab,
    texture_suppress,
    apply_gray_world,
    apply_shading_correction,
    coarse_lighting_range,
    delta_components,
    build_recommendations,
    make_quality_flags,
    build_capture_guidance,
    resolve_targets,
    ciede2000 as ciede2000_np,
)

# SENIA 模块 (只导入实际使用的)
from senia_recipe import generate_recipe_advice


# ══════════════════════════════════════════════════════════
# 三级判定: 合格 / 临界 / 不合格
# ══════════════════════════════════════════════════════════

def _three_tier_from_metrics(
    avg_de: float,
    p95_de: float,
    max_de: float,
    confidence_overall: float,
    profile_name: str,
    defect_severity: float = 0.0,
) -> dict[str, Any]:
    """
    三级判定 (替代原有的 pass/fail 二元判定).

    返回:
      tier: "PASS" / "MARGINAL" / "FAIL"
      reasons: 判定原因列表
    """
    # 按材质的阈值
    tier_thresholds = {
        "solid":     {"pass_avg": 1.0, "marginal_avg": 2.0, "pass_p95": 1.8, "marginal_p95": 3.0},
        "wood":      {"pass_avg": 1.2, "marginal_avg": 2.8, "pass_p95": 2.2, "marginal_p95": 4.0},
        "stone":     {"pass_avg": 1.5, "marginal_avg": 3.2, "pass_p95": 2.8, "marginal_p95": 4.5},
        "metallic":  {"pass_avg": 0.8, "marginal_avg": 2.2, "pass_p95": 1.6, "marginal_p95": 3.0},
        "high_gloss":{"pass_avg": 0.6, "marginal_avg": 1.8, "pass_p95": 1.2, "marginal_p95": 2.5},
    }
    t = tier_thresholds.get(profile_name, tier_thresholds["wood"])

    reasons = []

    # 基于色差
    if avg_de <= t["pass_avg"] and p95_de <= t["pass_p95"]:
        tier = "PASS"
        reasons.append(f"avg ΔE={avg_de:.2f}≤{t['pass_avg']}, p95 ΔE={p95_de:.2f}≤{t['pass_p95']} → 合格")
    elif avg_de <= t["marginal_avg"] and p95_de <= t["marginal_p95"]:
        tier = "MARGINAL"
        reasons.append(f"avg ΔE={avg_de:.2f} 在临界范围 ({t['pass_avg']}~{t['marginal_avg']})")
    else:
        tier = "FAIL"
        reasons.append(f"avg ΔE={avg_de:.2f}>{t['marginal_avg']} → 不合格")

    # 置信度降级
    if confidence_overall < 0.65:
        if tier == "PASS":
            tier = "MARGINAL"
            reasons.append(f"置信度偏低 ({confidence_overall:.2f}<0.65), 降为临界, 建议重拍")

    # 缺陷降级
    if defect_severity > 0.6:
        if tier != "FAIL":
            tier = "FAIL"
            reasons.append(f"检测到明显缺陷 (严重度={defect_severity:.2f}), 降为不合格")
    elif defect_severity > 0.3:
        if tier == "PASS":
            tier = "MARGINAL"
            reasons.append(f"检测到轻微缺陷 (严重度={defect_severity:.2f}), 降为临界")

    return {"tier": tier, "reasons": reasons}


# ══════════════════════════════════════════════════════════
# 偏差方向: 偏红/偏黄/偏暗/偏灰/饱和度不足
# ══════════════════════════════════════════════════════════

def _deviation_directions(dL: float, dC: float, dH: float,
                          board_lab: np.ndarray, sample_lab: np.ndarray) -> dict[str, Any]:
    """把 Lab 偏差翻译成操作员能看懂的方向描述."""
    da = float(sample_lab[1] - board_lab[1])
    db = float(sample_lab[2] - board_lab[2])

    dirs = []
    if abs(dL) > 0.5:
        dirs.append("偏亮" if dL > 0 else "偏暗")
    if abs(da) > 0.5:
        dirs.append("偏红" if da > 0 else "偏绿")
    if abs(db) > 0.5:
        dirs.append("偏黄" if db > 0 else "偏蓝")
    if abs(dC) > 0.5:
        dirs.append("饱和度偏高" if dC > 0 else "饱和度不足/偏灰")

    return {
        "directions": dirs,
        "summary": "".join(dirs) if dirs else "色差极小",
        "dL": round(dL, 4),
        "da": round(da, 4),
        "db": round(db, 4),
        "dC": round(dC, 4),
        "dH_deg": round(dH, 4),
    }


# ══════════════════════════════════════════════════════════
# 空间均匀性: 配方 vs 工艺
# ══════════════════════════════════════════════════════════

def _spatial_uniformity(grid: list[dict[str, Any]]) -> dict[str, Any]:
    """从网格色差数据判断: 均匀偏色=配方, 不均匀=工艺."""
    de_values = [float(c["delta_e00"]) for c in grid if c.get("used") and c.get("delta_e00") is not None]
    if len(de_values) < 4:
        return {"root_cause": "unknown", "explanation": "有效网格不足", "cv": 0.0}

    import statistics
    mean_de = statistics.mean(de_values)
    std_de = statistics.stdev(de_values) if len(de_values) > 1 else 0.0
    cv = std_de / max(mean_de, 1e-6)

    # L 通道均匀性 (用于发花检测)
    l_values = [float(c.get("cell_L", 50)) for c in grid if c.get("used")]

    if mean_de < 0.5:
        return {"root_cause": "ok", "explanation": "色差极小, 无需调整",
                "cv": round(cv, 4), "mean_dE": round(mean_de, 2)}

    if cv < 0.25:
        return {
            "root_cause": "recipe",
            "explanation": f"整版均匀偏色 (CV={cv:.3f}<0.25), 大概率配方问题",
            "cv": round(cv, 4), "mean_dE": round(mean_de, 2),
        }
    else:
        return {
            "root_cause": "process",
            "explanation": f"偏色不均匀 (CV={cv:.3f}≥0.25), 大概率工艺问题 (刮刀/烘干/涂布)",
            "cv": round(cv, 4), "mean_dE": round(mean_de, 2),
        }


# ══════════════════════════════════════════════════════════
# 调色建议
# ══════════════════════════════════════════════════════════

def _recipe_advice(dL: float, da: float, db: float, dC: float,
                   root_cause: str, tier: str) -> dict[str, Any]:
    """生成调色/工艺建议."""
    result = generate_recipe_advice(
        dL=dL, da=da, db=db, dC=dC,
        root_cause=root_cause,
    )
    return {
        "root_cause": result.root_cause,
        "is_process_issue": result.is_process_issue,
        "summary": result.summary,
        "advices": [
            {"action": a.action, "priority": a.priority, "category": a.category,
             "component": a.component, "direction": a.direction}
            for a in result.advices
        ],
    }


# ══════════════════════════════════════════════════════════
# 主入口: 从一张照片到完整结果
# ══════════════════════════════════════════════════════════

def analyze_photo(
    image_path: str | Path,
    profile_name: str = "auto",
    output_dir: str | Path | None = None,
    grid_rows: int = 6,
    grid_cols: int = 8,
    target_override: dict[str, float] | None = None,
    enable_shading_correction: bool = True,
    lot_id: str = "",
    product_code: str = "",
    sample_rect: tuple[int, int, int, int] | None = None,  # (x, y, w, h) 手动框选标样区域
) -> dict[str, Any]:
    """
    ★ 完整自动对色入口 — 从一张原始照片到最终判定+调色建议.

    参数:
      image_path: 原始照片路径 (iPhone ProRAW/JPEG/PNG)
      profile_name: "auto" / "wood" / "solid" / "stone" / "metallic" / "high_gloss"
      output_dir: 输出目录 (热图/标注图/JSON 会保存到此)
      grid_rows, grid_cols: 网格尺寸
      lot_id, product_code: 批次/产品信息

    返回:
      完整结果字典, 包含:
        - tier: "PASS" / "MARGINAL" / "FAIL"
        - deviation: 偏差方向 (偏红/偏黄/偏暗/偏灰)
        - recipe_advice: 调色建议
        - uniformity: 配方 vs 工艺根因
        - 原有所有字段 (色差/置信度/网格/热图/...)
    """
    start_time = time.perf_counter()
    image_path = Path(image_path)

    if output_dir is None:
        output_dir = image_path.parent / "senia_output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 读取图像 ──
    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise FileNotFoundError(f"无法读取图像: {image_path}")

    # ── 1.5 图像质量预检 ──
    from senia_preflight import preflight_check, detect_wet_or_film
    preflight = preflight_check(image_bgr)
    if not preflight["ok"]:
        error_text = "照片质量不合格，无法分析:\n" + "\n".join(f"• {e}" for e in preflight["errors"])
        if preflight["warnings"]:
            error_text += "\n" + "\n".join(f"• {w}" for w in preflight["warnings"])
        raise RuntimeError(error_text)

    # 湿板/保护膜检测
    wet_film = detect_wet_or_film(image_bgr)

    # ── 2. 检测大货和标样区域 ──
    # 优先级: 手动框选 > ArUco > 轮廓检测

    # 如果操作员手动框选了标样区域, 直接使用
    if sample_rect is not None:
        sx, sy, sw, sh = sample_rect
        sample_quad = np.array([
            [sx, sy], [sx + sw, sy], [sx + sw, sy + sh], [sx, sy + sh]
        ], dtype=np.float32)
        # Board = 整张图减去标样
        h_img, w_img = image_bgr.shape[:2]
        board_quad = np.array([
            [0, 0], [w_img, 0], [w_img, h_img], [0, h_img]
        ], dtype=np.float32)
        sample_source = "manual"
        det_diag = {"candidates": 0, "board_area_ratio": 1.0, "sample_area_ratio_to_board": (sw * sh) / (w_img * h_img)}
    else:
        sample_quad = None

    if sample_quad is None:
        # 自动检测: 先尝试 ArUco, 再退回轮廓检测
        aruco_quad, aruco_info = detect_aruco_board_quad(image_bgr)
        if aruco_quad is not None:
            board_quad = aruco_quad
            sample_source = "aruco"
            cands = contour_candidates(image_bgr)
            _, sample_cand, det_diag = choose_board_and_sample(cands, image_bgr.shape, image_bgr)
            sample_quad = order_quad(sample_cand.quad) if sample_cand else None
        else:
            cands = contour_candidates(image_bgr)
            board_cand, sample_cand, det_diag = choose_board_and_sample(cands, image_bgr.shape, image_bgr)
            if board_cand is None:
                raise RuntimeError("未检测到大货区域, 请确保整版膜在画面中居中且与背景有对比度")
        board_quad = order_quad(board_cand.quad)
        sample_quad = order_quad(sample_cand.quad) if sample_cand is not None else None
        sample_source = "contour"

    has_sample = sample_quad is not None
    if not has_sample:
        raise RuntimeError(
            "未检测到标样区域, 无法进行对色判定。"
            "请确保标样放在大货旁边或上方, 且标样面积占大货的 1.5%~50%。"
            "如果标样和大货颜色非常接近, 请在标样边缘贴定位标记以辅助检测。"
        )

    # ── 3. 透视校正 ──
    board_warp, board_M, board_rect = warp_quad(image_bgr, board_quad)

    sample_warp, sample_M, sample_rect = warp_quad(image_bgr, sample_quad)

    # ── 4. 构建遮罩 (K-means 分割 + fallback) ──
    try:
        from senia_advanced_color import smart_board_segment
        orig_seg = smart_board_segment(image_bgr)
        bh, bw = board_warp.shape[:2]
        seg_warped = cv2.warpPerspective(
            (orig_seg * 255).astype(np.uint8), board_M, (bw, bh),
            flags=cv2.INTER_NEAREST
        )
        board_mask = seg_warped > 127
        border_mask = build_material_mask(board_warp.shape[:2], border_ratio=0.03)
        board_mask &= border_mask
        # fallback: 如果 K-means 过滤太多 (<30% 有效), 用标准 mask
        if np.count_nonzero(board_mask) < board_mask.size * 0.30:
            board_mask = build_material_mask(board_warp.shape[:2], border_ratio=0.04)
    except Exception:
        board_mask = build_material_mask(board_warp.shape[:2], border_ratio=0.04)
    board_invalid = build_invalid_mask(board_warp)
    board_mask &= ~board_invalid

    # 遮罩掉标样所在区域 (仅当标样在大货上面时)
    board_poly = board_quad.reshape(-1, 1, 2).astype(np.float32)
    sample_center = sample_quad.mean(axis=0)
    sample_inside_board = cv2.pointPolygonTest(board_poly, tuple(sample_center), measureDist=False) >= 0
    if sample_inside_board:
        sample_on_board = cv2.perspectiveTransform(
            sample_quad.reshape(1, -1, 2), board_M
        ).reshape(-1, 2)
        board_mask_u8 = board_mask.astype(np.uint8)
        cv2.fillConvexPoly(board_mask_u8, sample_on_board.astype(np.int32), 0)
        board_mask = board_mask_u8.astype(bool)

    sample_mask = None
    sample_mask = build_material_mask(sample_warp.shape[:2], border_ratio=0.06)
    sample_invalid = build_invalid_mask(sample_warp)
    sample_mask &= ~sample_invalid

    # ── 5. 白平衡 + 光照均匀性校正 ──
    # 关键: 大货和标样必须用相同的WB增益, 否则相对色差被破坏.
    # 在工厂荧光灯/LED灯下, 绝对色值可能偏, 但相对色差是准的.
    board_wb, board_gains = apply_gray_world(board_warp, board_mask)
    # 对标样用大货的WB增益 (保持相对一致性, 比各自独立WB更可靠)
    sample_wb = sample_warp.copy().astype(np.float32)
    for ch in range(3):
        sample_wb[..., ch] = np.clip(sample_warp[..., ch].astype(np.float32) * board_gains[ch], 0, 255)
    sample_wb = sample_wb.astype(np.uint8)
    sample_gains = board_gains  # 记录: 用了相同增益

    if enable_shading_correction:
        board_wb = apply_shading_correction(board_wb, board_mask)
        sample_wb = apply_shading_correction(sample_wb, sample_mask)

    # ── 6. 纹理抑制 (自适应: 根据纹理强度自动调节) ──
    try:
        from senia_advanced_color import adaptive_texture_suppress, weighted_robust_mean
        board_tone = adaptive_texture_suppress(board_wb, board_mask.astype(np.uint8) if isinstance(board_mask, np.ndarray) else None)
        board_lab = bgr_to_lab_float(board_tone)
        board_mean, _conf = weighted_robust_mean(board_lab, board_mask.astype(np.uint8) if board_mask.dtype == bool else board_mask)
        board_std = np.zeros(3)
        board_used = int(np.count_nonzero(board_mask))
    except (ImportError, ValueError, cv2.error):  # fallback to basic if advanced unavailable
        board_tone = texture_suppress(board_wb)
        board_lab = bgr_to_lab_float(board_tone)
        board_mean, board_std, board_used = robust_mean_lab(board_lab, board_mask)

    # sample is guaranteed present (validated above)
    try:
        sample_tone = adaptive_texture_suppress(sample_wb, sample_mask.astype(np.uint8) if isinstance(sample_mask, np.ndarray) else None)
        sample_lab = bgr_to_lab_float(sample_tone)
        sample_mean, _sconf = weighted_robust_mean(sample_lab, sample_mask.astype(np.uint8) if sample_mask.dtype == bool else sample_mask)
        sample_std = np.zeros(3)
        sample_used = int(np.count_nonzero(sample_mask))
    except (ImportError, ValueError, cv2.error):  # fallback to basic
        sample_tone = texture_suppress(sample_wb)
        sample_lab = bgr_to_lab_float(sample_tone)
        sample_mean, sample_std, sample_used = robust_mean_lab(sample_lab, sample_mask)

    # ── 7. 材质自动识别 ──
    inferred_profile, profile_metrics = infer_profile(board_tone, board_mask, profile_name)
    profile = PROFILES[inferred_profile]

    # ── 8. 网格分析 (两阶段: 先自参考找异常, 再计算真实色差) ──
    grid: list[dict[str, Any]] = []
    all_cells: list[dict[str, Any]] = []
    h, w = board_mask.shape

    # 第一遍: 每个格子 vs 全局均值 (自参考)
    for r in range(grid_rows):
        y0 = int(round(r * h / grid_rows))
        y1 = int(round((r + 1) * h / grid_rows))
        for c in range(grid_cols):
            x0 = int(round(c * w / grid_cols))
            x1 = int(round((c + 1) * w / grid_cols))
            cell_mask = board_mask[y0:y1, x0:x1]
            used = bool(np.count_nonzero(cell_mask) >= max(80, int(cell_mask.size * 0.15)))
            if not used:
                grid.append({"row": r+1, "col": c+1, "used": False, "delta_e00": None, "cell_L": None})
                continue
            cell_mean_arr, cell_std, cnt = robust_mean_lab(board_lab[y0:y1, x0:x1], cell_mask)
            de_self = float(ciede2000_np(cell_mean_arr.reshape(1, 3), board_mean.reshape(1, 3))[0])
            cell_info = {
                "row": r+1, "col": c+1, "used": True,
                "cell_mean": cell_mean_arr, "de_self": de_self,
                "cell_L": round(float(cell_mean_arr[0]), 2),
                "cell_a": round(float(cell_mean_arr[1]), 2),
                "cell_b": round(float(cell_mean_arr[2]), 2),
            }
            all_cells.append(cell_info)
            grid.append({"row": r+1, "col": c+1, "used": True, "delta_e00": round(de_self, 4),
                          "cell_L": cell_info["cell_L"], "cell_a": cell_info["cell_a"], "cell_b": cell_info["cell_b"]})

    if not all_cells:
        raise RuntimeError("可用采样网格为空, 请检查图像质量")

    # 第二遍: 区分大货格子 vs 标样格子
    # 标样特征: ΔE 偏大但 L 值和大货相近 (差 < 8)
    # 手写字/背景特征: ΔE 偏大且 L 值和大货差很远 (差 > 8)
    all_de_self = [c["de_self"] for c in all_cells]
    all_L = [float(c["cell_mean"][0]) for c in all_cells]
    import statistics as _stats
    median_L = _stats.median(all_L) if all_L else 50
    de_median = _stats.median(all_de_self) if all_de_self else 0
    de_mad = _stats.median([abs(d - de_median) for d in all_de_self]) if len(all_de_self) > 2 else 1
    outlier_threshold = de_median + max(3.0 * de_mad, 1.5)

    # 标样 = ΔE 高但 L 接近大货; 噪声 = ΔE 高且 L 远离大货
    sample_cells = []
    noise_cells = []
    board_cells = []
    for c in all_cells:
        if c["de_self"] > outlier_threshold:
            L_diff = abs(float(c["cell_mean"][0]) - median_L)
            if L_diff < 8:
                sample_cells.append(c)  # L 接近 → 可能是标样
            else:
                noise_cells.append(c)   # L 远离 → 手写字/背景
        else:
            board_cells.append(c)

    # 参考值选择: 标样格子均值 → 大货均值 (内部一致性)
    if sample_cells and len(sample_cells) >= 1:
        ref_lab = np.mean([c["cell_mean"] for c in sample_cells], axis=0)
        ref_vec = ref_lab.reshape(1, 3)
    elif board_cells:
        # 无标样: 用大货格子均值作为参考 → 测量内部一致性
        ref_lab = np.mean([c["cell_mean"] for c in board_cells], axis=0)
        ref_vec = ref_lab.reshape(1, 3)
    else:
        ref_vec = sample_mean.reshape(1, 3)

    # 第三遍: 大货格子 vs 参考值 → 色差
    de_values: list[float] = []
    for cell_info in board_cells:
        de = float(ciede2000_np(cell_info["cell_mean"].reshape(1, 3), ref_vec)[0])
        de_values.append(de)
        # 更新 grid 中的 delta_e00
        for g in grid:
            if g["row"] == cell_info["row"] and g["col"] == cell_info["col"]:
                g["delta_e00"] = round(de, 4)
                break

    if not de_values:
        de_values = all_de_self  # fallback

    # ── 9. 统计指标 ──
    de_np = np.array(de_values, dtype=np.float32)
    avg_de = float(np.mean(de_np))
    p95_de = float(np.percentile(de_np, 95))

    # 一致性检查: 如果网格分析的 avg 远大于 global, 可能异常值排除有误
    de_global_check = float(ciede2000_np(board_mean.reshape(1, 3), sample_mean.reshape(1, 3))[0])
    if avg_de > de_global_check * 3 and de_global_check < 20:
        # 网格分析结果不可靠, 回退到 global 色差
        avg_de = de_global_check
        p95_de = de_global_check * 1.3
    max_de = float(np.max(de_np))
    de_global = float(ciede2000_np(board_mean.reshape(1, 3), sample_mean.reshape(1, 3))[0])
    d_l, d_c, d_h = delta_components(board_mean, sample_mean)

    # ── 10. 置信度 ──
    lighting_range = coarse_lighting_range(board_lab, board_mask)
    board_valid_ratio = float(np.count_nonzero(board_mask) / board_mask.size)
    sample_valid_ratio = float(np.count_nonzero(sample_mask) / sample_mask.size)
    confidence = compute_confidence(det_diag, lighting_range, board_valid_ratio, sample_valid_ratio)

    # ══════════════════════════════════════════════════════
    # ★ 新增能力: 三级判定 + 偏差方向 + 调色建议 + 根因分析
    # ══════════════════════════════════════════════════════

    # 三级判定
    tier_result = _three_tier_from_metrics(
        avg_de, p95_de, max_de,
        confidence["overall"], inferred_profile,
    )

    # 偏差方向
    deviation = _deviation_directions(d_l, d_c, d_h, board_mean, sample_mean)

    # 空间均匀性 → 配方 vs 工艺
    uniformity = _spatial_uniformity(grid)

    # 调色建议
    recipe = _recipe_advice(
        dL=d_l, da=deviation["da"], db=deviation["db"], dC=d_c,
        root_cause=uniformity["root_cause"],
        tier=tier_result["tier"],
    )

    # ── Next-Gen 自动嵌入 ──
    try:
        from senia_next_gen import metamerism_risk, delta_e_to_cost
        metamerism = metamerism_risk((float(board_mean[0]), float(board_mean[1]), float(board_mean[2])))
        cost = delta_e_to_cost(avg_de)
    except (ImportError, ValueError, TypeError):
        metamerism = {"risk_level": "unknown"}
        cost = {}

    # ══════════════════════════════════════════════════════
    # 输出可视化
    # ══════════════════════════════════════════════════════

    # 热图
    heatmap_path = output_dir / "heatmap.png"
    draw_heatmap_on_board(board_warp, grid_rows, grid_cols, grid, heatmap_path)

    # 标注图 (大货/标样边框)
    overlay_path = output_dir / "detection.png"
    draw_detection_overlay(image_bgr, board_quad, sample_quad, overlay_path)

    # 大货/标样校正后图片
    cv2.imwrite(str(output_dir / "board_corrected.png"), board_warp)
    cv2.imwrite(str(output_dir / "sample_corrected.png"), sample_warp)

    elapsed = time.perf_counter() - start_time

    # 兼容原有字段 + 新增字段
    t = resolve_targets(profile["targets"], target_override)
    pass_color = avg_de <= t["avg_delta_e00"] and p95_de <= t["p95_delta_e00"] and max_de <= t["max_delta_e00"]
    recs = build_recommendations(d_l, d_c, d_h, profile["bias_thresholds"], confidence["overall"])
    quality_flags = make_quality_flags(
        confidence=confidence, lighting_range=lighting_range,
        board_valid_ratio=board_valid_ratio, sample_valid_ratio=sample_valid_ratio,
        p95_delta_e=p95_de, max_delta_e=max_de,
        board_sharpness=0, sample_sharpness=0,
    )

    # 智能建议: 单拍 ΔE 偏高时建议双拍复核
    smart_tip = ""
    if avg_de > 5.0:
        smart_tip = "💡 建议使用「两张照片」模式复核 — 标样和大货分别拍摄，精度更高"
    elif avg_de > 3.0:
        smart_tip = "ℹ️ 如需更精确的结果，可切换到「两张照片」模式"

    report = {
        "mode": "auto_match",
        "image": str(image_path),
        "lot_id": lot_id,
        "product_code": product_code,
        "elapsed_sec": round(elapsed, 3),
        "smart_tip": smart_tip,

        # ★ 核心输出: 操作员直接看这些
        "tier": tier_result["tier"],             # "PASS" / "MARGINAL" / "FAIL"
        "tier_reasons": tier_result["reasons"],
        "deviation": deviation,                   # 偏差方向
        "recipe_advice": recipe,                  # 调色建议
        "uniformity": uniformity,                 # 配方 vs 工艺

        # 质量预检
        "preflight": {
            "quality": preflight.get("quality", "unknown"),
            "warnings": preflight.get("warnings", []),
            "scores": preflight.get("scores", {}),
        },
        "surface_check": wet_film if wet_film.get("detected") else {"detected": False},
        "metamerism": metamerism,
        "cost_risk": cost,

        # 详细数据
        "profile": {
            "requested": profile_name,
            "used": inferred_profile,
            "metrics": profile_metrics,
            "targets": profile["targets"],
            "targets_used": t,
        },
        "detection": {
            **det_diag,
            "sample_source": sample_source,
            "has_sample": True,
        },
        "result": {
            "pass_legacy": pass_color,  # 原有二元判定 (向后兼容)
            "confidence": confidence,
            "summary": {
                "global_delta_e00": de_global,
                "avg_delta_e00": avg_de,
                "p50_delta_e00": float(np.percentile(de_np, 50)),
                "p95_delta_e00": p95_de,
                "max_delta_e00": max_de,
                "dL": d_l, "dC": d_c, "dH_deg": d_h,
                "board_lab": [float(x) for x in board_mean],
                "sample_lab": [float(x) for x in sample_mean],
            },
            "recommendations": recs,
            "quality_flags": quality_flags,
            "capture_guidance": build_capture_guidance(quality_flags),
            "grid": grid,
        },
        "artifacts": {
            "heatmap": str(heatmap_path),
            "detection_overlay": str(overlay_path),
            "board_corrected": str(output_dir / "board_corrected.png"),
            "sample_corrected": str(output_dir / "sample_corrected.png"),
        },
    }

    # 保存 JSON 报告
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    return report


# ══════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="SENIA 自动对色 — 从照片到判定")
    parser.add_argument("image", type=str, help="照片路径")
    parser.add_argument("--profile", type=str, default="auto", help="材质: auto/wood/solid/stone/metallic/high_gloss")
    parser.add_argument("--output", type=str, default=None, help="输出目录")
    parser.add_argument("--grid", type=str, default="6x8", help="网格尺寸 (如 6x8)")
    parser.add_argument("--lot", type=str, default="", help="批次号")
    parser.add_argument("--product", type=str, default="", help="产品编号")
    args = parser.parse_args()

    rows, cols = [int(x) for x in args.grid.split("x")]

    report = analyze_photo(
        image_path=args.image,
        profile_name=args.profile,
        output_dir=args.output,
        grid_rows=rows,
        grid_cols=cols,
        lot_id=args.lot,
        product_code=args.product,
    )

    # 打印操作员看得懂的结果
    print("=" * 55)
    print("  SENIA 自动对色结果")
    print("=" * 55)
    print(f"  判定:  {report['tier']}")
    print(f"  色差:  ΔE00 = {report['result']['summary']['avg_delta_e00']:.2f} (avg)")
    print(f"  偏差:  {report['deviation']['summary']}")
    print(f"  材质:  {report['profile']['used']}")
    print(f"  根因:  {report['uniformity'].get('explanation', '-')}")
    print()

    if report["tier"] != "PASS":
        print("  调色建议:")
        for a in report["recipe_advice"].get("advices", [])[:5]:
            print(f"    {a['action']}")
        print()

    for r in report["tier_reasons"]:
        print(f"  • {r}")

    print(f"\n  耗时: {report['elapsed_sec']:.2f}s")
    print(f"  报告: {report['artifacts']['heatmap']}")
    print("=" * 55)


if __name__ == "__main__":
    main()
