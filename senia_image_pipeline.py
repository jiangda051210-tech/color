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
    ROI,
    RectCandidate,
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
    perspective_warp,
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

# SENIA 新模块
from senia_calibration import ciede2000 as ciede2000_scalar
from senia_analysis import (
    ThresholdConfig,
    run_full_analysis as senia_full_analysis,
    compute_color_deviation,
    run_defect_pipeline,
    judge_three_tier,
    analyze_spatial_uniformity,
)
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

    # ── 2. 检测大货和标样区域 ──
    # 先尝试 ArUco, 再退回轮廓检测
    aruco_quad, aruco_info = detect_aruco_board_quad(image_bgr)
    if aruco_quad is not None:
        board_quad = aruco_quad
        sample_source = "aruco"
        cands = contour_candidates(image_bgr)
        _, sample_cand, det_diag = choose_board_and_sample(cands, image_bgr.shape)
        sample_quad = order_quad(sample_cand.quad) if sample_cand else None
    else:
        cands = contour_candidates(image_bgr)
        board_cand, sample_cand, det_diag = choose_board_and_sample(cands, image_bgr.shape)
        if board_cand is None:
            raise RuntimeError("未检测到大货区域, 请确保整版膜在画面中居中且与背景有对比度")
        board_quad = order_quad(board_cand.quad)
        sample_quad = order_quad(sample_cand.quad) if sample_cand is not None else None
        sample_source = "contour"

    has_sample = sample_quad is not None

    # ── 3. 透视校正 ──
    board_warp, board_M, board_rect = perspective_warp(image_bgr, board_quad)

    if has_sample:
        sample_warp, sample_M, sample_rect = perspective_warp(image_bgr, sample_quad)
        # 计算标样在大货坐标系中的位置 (用于遮罩)
        sample_center = sample_quad.mean(axis=0)
        sample_on_board = cv2.perspectiveTransform(
            sample_quad.reshape(1, -1, 2), board_M
        ).reshape(-1, 2)
    else:
        # 无标样: 无法对色, 只做单板分析
        sample_warp = None

    # ── 4. 构建遮罩 (去除边框 + 手写/贴纸/反光) ──
    board_mask = build_material_mask(board_warp.shape[:2], border_ratio=0.04)
    board_invalid = build_invalid_mask(board_warp)
    board_mask &= ~board_invalid

    # 遮罩掉标样所在区域 (如果标样放在大货上)
    if has_sample:
        board_mask_u8 = board_mask.astype(np.uint8)
        cv2.fillConvexPoly(board_mask_u8, sample_on_board.astype(np.int32), 0)
        board_mask = board_mask_u8.astype(bool)

    sample_mask = None
    if has_sample and sample_warp is not None:
        sample_mask = build_material_mask(sample_warp.shape[:2], border_ratio=0.06)
        sample_invalid = build_invalid_mask(sample_warp)
        sample_mask &= ~sample_invalid

    # ── 5. 白平衡 + 光照均匀性校正 ──
    board_wb, board_gains = apply_gray_world(board_warp, board_mask)
    if enable_shading_correction:
        board_wb = apply_shading_correction(board_wb, board_mask)

    if has_sample and sample_warp is not None and sample_mask is not None:
        sample_wb, sample_gains = apply_gray_world(sample_warp, sample_mask)
        if enable_shading_correction:
            sample_wb = apply_shading_correction(sample_wb, sample_mask)
    else:
        sample_wb = None
        sample_gains = [1.0, 1.0, 1.0]

    # ── 6. 纹理抑制 (木纹膜关键: 对底色不对纹理) ──
    board_tone = texture_suppress(board_wb)
    board_lab = bgr_to_lab_float(board_tone)
    board_mean, board_std, board_used = robust_mean_lab(board_lab, board_mask)

    if has_sample and sample_wb is not None and sample_mask is not None:
        sample_tone = texture_suppress(sample_wb)
        sample_lab = bgr_to_lab_float(sample_tone)
        sample_mean, sample_std, sample_used = robust_mean_lab(sample_lab, sample_mask)
    else:
        sample_lab = board_lab
        sample_mean = board_mean
        sample_std = board_std
        sample_used = 0

    # ── 7. 材质自动识别 ──
    inferred_profile, profile_metrics = infer_profile(board_tone, board_mask, profile_name)
    profile = PROFILES[inferred_profile]

    # ── 8. 网格分析 (每个小块 vs 标样) ──
    grid: list[dict[str, Any]] = []
    de_values: list[float] = []
    h, w = board_mask.shape
    sample_vec = sample_mean.reshape(1, 3)

    for r in range(grid_rows):
        y0 = int(round(r * h / grid_rows))
        y1 = int(round((r + 1) * h / grid_rows))
        for c in range(grid_cols):
            x0 = int(round(c * w / grid_cols))
            x1 = int(round((c + 1) * w / grid_cols))
            cell_mask = board_mask[y0:y1, x0:x1]
            used = bool(np.count_nonzero(cell_mask) >= max(80, int(cell_mask.size * 0.28)))
            if not used:
                grid.append({"row": r + 1, "col": c + 1, "used": False, "delta_e00": None, "cell_L": None})
                continue
            cell_mean, cell_std, cnt = robust_mean_lab(board_lab[y0:y1, x0:x1], cell_mask)
            de = float(ciede2000_np(cell_mean.reshape(1, 3), sample_vec)[0])
            de_values.append(de)
            grid.append({
                "row": r + 1, "col": c + 1, "used": True,
                "delta_e00": round(de, 4),
                "cell_L": round(float(cell_mean[0]), 2),
                "cell_a": round(float(cell_mean[1]), 2),
                "cell_b": round(float(cell_mean[2]), 2),
            })

    if not de_values:
        raise RuntimeError("可用采样网格为空, 请检查图像质量")

    # ── 9. 统计指标 ──
    de_np = np.array(de_values, dtype=np.float32)
    avg_de = float(np.mean(de_np))
    p95_de = float(np.percentile(de_np, 95))
    max_de = float(np.max(de_np))
    de_global = float(ciede2000_np(board_mean.reshape(1, 3), sample_mean.reshape(1, 3))[0])
    d_l, d_c, d_h = delta_components(board_mean, sample_mean)

    # ── 10. 置信度 ──
    lighting_range = coarse_lighting_range(board_lab, board_mask)
    board_valid_ratio = float(np.count_nonzero(board_mask) / board_mask.size)
    sample_valid_ratio = float(np.count_nonzero(sample_mask) / sample_mask.size) if sample_mask is not None else 0.5
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
    if has_sample and sample_warp is not None:
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

    report = {
        "mode": "auto_match",
        "image": str(image_path),
        "lot_id": lot_id,
        "product_code": product_code,
        "elapsed_sec": round(elapsed, 3),

        # ★ 核心输出: 操作员直接看这些
        "tier": tier_result["tier"],             # "PASS" / "MARGINAL" / "FAIL"
        "tier_reasons": tier_result["reasons"],
        "deviation": deviation,                   # 偏差方向
        "recipe_advice": recipe,                  # 调色建议
        "uniformity": uniformity,                 # 配方 vs 工艺

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
            "has_sample": has_sample,
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
            "sample_corrected": str(output_dir / "sample_corrected.png") if has_sample else None,
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
