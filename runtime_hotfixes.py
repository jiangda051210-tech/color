"""
Runtime hotfix wrappers for critical regressions.

Use these drop-in entry points when you need the same behavior as the
original pipelines, but with a few high-value fixes applied immediately:

1) senia_image_pipeline.analyze_photo
   - fixes the ArUco branch variable overwrite / undefined board_cand path
   - fixes coarse_lighting_range dict -> float usage before confidence scoring

2) elite_color_match.analyze_dual_image
   - fixes the undefined gain_film reference in preprocess output

These wrappers intentionally keep the original return schema so they can be
adopted incrementally without forcing a large refactor.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import elite_color_match as ecm
import senia_image_pipeline as sip


__all__ = ["analyze_photo_fixed", "analyze_dual_image_fixed"]


def analyze_photo_fixed(
    image_path: str | Path,
    profile_name: str = "auto",
    output_dir: str | Path | None = None,
    grid_rows: int = 6,
    grid_cols: int = 8,
    target_override: dict[str, float] | None = None,
    enable_shading_correction: bool = True,
    lot_id: str = "",
    product_code: str = "",
    sample_rect: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    image_path = Path(image_path)

    if output_dir is None:
        output_dir = image_path.parent / "senia_output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise FileNotFoundError(f"无法读取图像: {image_path}")

    from senia_preflight import preflight_check, detect_wet_or_film

    preflight = preflight_check(image_bgr)
    if not preflight["ok"]:
        error_text = "照片质量不合格，无法分析:\n" + "\n".join(f"• {e}" for e in preflight["errors"])
        if preflight["warnings"]:
            error_text += "\n" + "\n".join(f"• {w}" for w in preflight["warnings"])
        raise RuntimeError(error_text)

    wet_film = detect_wet_or_film(image_bgr)

    # --- Detection hotfix ---
    if sample_rect is not None:
        sx, sy, sw, sh = sample_rect
        sample_quad = np.array(
            [[sx, sy], [sx + sw, sy], [sx + sw, sy + sh], [sx, sy + sh]],
            dtype=np.float32,
        )
        h_img, w_img = image_bgr.shape[:2]
        board_quad = np.array([[0, 0], [w_img, 0], [w_img, h_img], [0, h_img]], dtype=np.float32)
        sample_source = "manual"
        det_diag = {
            "candidates": 0,
            "board_area_ratio": 1.0,
            "sample_area_ratio_to_board": (sw * sh) / max(w_img * h_img, 1),
            "aruco": {"found": False, "enabled": False},
            "aruco_applied": False,
        }
    else:
        cands = ecm.contour_candidates(image_bgr)
        board_cand = None
        sample_cand = None
        aruco_quad, aruco_info = ecm.detect_aruco_board_quad(image_bgr)

        if aruco_quad is not None:
            board_quad = ecm.order_quad(aruco_quad)
            _, sample_cand, det_diag = ecm.choose_board_and_sample(cands, image_bgr.shape, image_bgr)
            sample_quad = ecm.order_quad(sample_cand.quad) if sample_cand is not None else None
            sample_source = "aruco"
            det_diag["aruco"] = aruco_info
            det_diag["aruco_applied"] = True
        else:
            board_cand, sample_cand, det_diag = ecm.choose_board_and_sample(cands, image_bgr.shape, image_bgr)
            if board_cand is None:
                raise RuntimeError("未检测到大货区域, 请确保整版膜在画面中居中且与背景有对比度")
            board_quad = ecm.order_quad(board_cand.quad)
            sample_quad = ecm.order_quad(sample_cand.quad) if sample_cand is not None else None
            sample_source = "contour"
            det_diag["aruco"] = aruco_info
            det_diag["aruco_applied"] = False

    if sample_quad is None:
        raise RuntimeError(
            "未检测到标样区域, 无法进行对色判定。"
            "请确保标样放在大货旁边或上方, 且标样面积占大货的 1.5%~50%。"
            "如果标样和大货颜色非常接近, 请在标样边缘贴定位标记以辅助检测。"
        )

    board_warp, board_M, _board_rect = ecm.warp_quad(image_bgr, board_quad)
    sample_warp, _sample_M, _sample_rect = ecm.warp_quad(image_bgr, sample_quad)

    try:
        from senia_advanced_color import smart_board_segment

        orig_seg = smart_board_segment(image_bgr)
        bh, bw = board_warp.shape[:2]
        seg_warped = cv2.warpPerspective(
            (orig_seg * 255).astype(np.uint8), board_M, (bw, bh), flags=cv2.INTER_NEAREST
        )
        board_mask = seg_warped > 127
        border_mask = ecm.build_material_mask(board_warp.shape[:2], border_ratio=0.03)
        board_mask &= border_mask
        if np.count_nonzero(board_mask) < board_mask.size * 0.30:
            board_mask = ecm.build_material_mask(board_warp.shape[:2], border_ratio=0.04)
    except Exception:
        board_mask = ecm.build_material_mask(board_warp.shape[:2], border_ratio=0.04)

    board_invalid = ecm.build_invalid_mask(board_warp)
    board_mask &= ~board_invalid

    board_poly = board_quad.reshape(-1, 1, 2).astype(np.float32)
    sample_center = sample_quad.mean(axis=0)
    sample_inside_board = cv2.pointPolygonTest(board_poly, tuple(sample_center), measureDist=False) >= 0
    if sample_inside_board:
        sample_on_board = cv2.perspectiveTransform(sample_quad.reshape(1, -1, 2), board_M).reshape(-1, 2)
        board_mask_u8 = board_mask.astype(np.uint8)
        cv2.fillConvexPoly(board_mask_u8, sample_on_board.astype(np.int32), 0)
        board_mask = board_mask_u8.astype(bool)

    sample_mask = ecm.build_material_mask(sample_warp.shape[:2], border_ratio=0.06)
    sample_invalid = ecm.build_invalid_mask(sample_warp)
    sample_mask &= ~sample_invalid

    board_wb, board_gains = ecm.apply_gray_world(board_warp, board_mask)
    sample_wb = sample_warp.copy().astype(np.float32)
    for ch in range(3):
        sample_wb[..., ch] = np.clip(sample_warp[..., ch].astype(np.float32) * board_gains[ch], 0, 255)
    sample_wb = sample_wb.astype(np.uint8)
    sample_gains = board_gains

    if enable_shading_correction:
        board_wb = ecm.apply_shading_correction(board_wb, board_mask)
        sample_wb = ecm.apply_shading_correction(sample_wb, sample_mask)

    try:
        from senia_advanced_color import adaptive_texture_suppress, weighted_robust_mean

        board_tone = adaptive_texture_suppress(
            board_wb, board_mask.astype(np.uint8) if isinstance(board_mask, np.ndarray) else None
        )
        board_lab = ecm.bgr_to_lab_float(board_tone)
        board_mean, _conf = weighted_robust_mean(
            board_lab, board_mask.astype(np.uint8) if board_mask.dtype == bool else board_mask
        )
        board_std = np.zeros(3)
        board_used = int(np.count_nonzero(board_mask))
    except (ImportError, ValueError, cv2.error):
        board_tone = ecm.texture_suppress(board_wb)
        board_lab = ecm.bgr_to_lab_float(board_tone)
        board_mean, board_std, board_used = ecm.robust_mean_lab(board_lab, board_mask)

    try:
        from senia_advanced_color import adaptive_texture_suppress, weighted_robust_mean

        sample_tone = adaptive_texture_suppress(
            sample_wb, sample_mask.astype(np.uint8) if isinstance(sample_mask, np.ndarray) else None
        )
        sample_lab = ecm.bgr_to_lab_float(sample_tone)
        sample_mean, _sconf = weighted_robust_mean(
            sample_lab, sample_mask.astype(np.uint8) if sample_mask.dtype == bool else sample_mask
        )
        sample_std = np.zeros(3)
        sample_used = int(np.count_nonzero(sample_mask))
    except (ImportError, ValueError, cv2.error):
        sample_tone = ecm.texture_suppress(sample_wb)
        sample_lab = ecm.bgr_to_lab_float(sample_tone)
        sample_mean, sample_std, sample_used = ecm.robust_mean_lab(sample_lab, sample_mask)

    inferred_profile, profile_metrics = ecm.infer_profile(board_tone, board_mask, profile_name)
    profile = ecm.PROFILES[inferred_profile]

    cc_dE = None
    try:
        from senia_advanced_color import smart_board_segment as _seg

        _fg = _seg(image_bgr)
        _eroded = cv2.erode(_fg, np.ones((5, 5), np.uint8), iterations=2)
        _n, _lmap, _stats, _ = cv2.connectedComponentsWithStats(_eroded)
        _regions = []
        for _i in range(1, _n):
            _a = _stats[_i, cv2.CC_STAT_AREA]
            if _a < 1000:
                continue
            _rw, _rh = _stats[_i, cv2.CC_STAT_WIDTH], _stats[_i, cv2.CC_STAT_HEIGHT]
            _asp = max(_rw, _rh) / (min(_rw, _rh) + 1)
            _regions.append((_i, _a, _asp))
        _regions.sort(key=lambda r: -r[1])
        if len(_regions) >= 2:
            _bid = _regions[0][0]
            _sid = None
            for _r in _regions[1:]:
                if _r[2] > 1.3 and _r[1] > image_bgr.shape[0] * image_bgr.shape[1] * 0.003:
                    _sid = _r[0]
                    break
            if _sid is not None:
                _bmask = cv2.dilate((_lmap == _bid).astype(np.uint8), np.ones((5, 5), np.uint8), iterations=2)
                _smask = cv2.dilate((_lmap == _sid).astype(np.uint8), np.ones((5, 5), np.uint8), iterations=2)
                _inv = ecm.build_invalid_mask(image_bgr)
                _bmask[_inv > 0] = 0
                _smask[_inv > 0] = 0
                if _bmask.sum() > 10000 and _smask.sum() > 2000:
                    try:
                        from senia_advanced_color import adaptive_texture_suppress as _at, weighted_robust_mean as _wr

                        _bt = _at(image_bgr, _bmask)
                        _bl = ecm.bgr_to_lab_float(_bt)
                        _bm, _ = _wr(_bl, _bmask)
                        _st = _at(image_bgr, _smask)
                        _sl = ecm.bgr_to_lab_float(_st)
                        _sm, _ = _wr(_sl, _smask)
                        _de = float(ecm.ciede2000(_bm.reshape(1, 3), _sm.reshape(1, 3))[0])
                        if _de < 30:
                            cc_dE = _de
                    except Exception:
                        pass
    except Exception:
        pass

    grid: list[dict[str, Any]] = []
    all_cells: list[dict[str, Any]] = []
    h, w = board_mask.shape
    for r in range(grid_rows):
        y0 = int(round(r * h / grid_rows))
        y1 = int(round((r + 1) * h / grid_rows))
        for c in range(grid_cols):
            x0 = int(round(c * w / grid_cols))
            x1 = int(round((c + 1) * w / grid_cols))
            cell_mask = board_mask[y0:y1, x0:x1]
            used = bool(np.count_nonzero(cell_mask) >= max(80, int(cell_mask.size * 0.15)))
            if not used:
                grid.append({"row": r + 1, "col": c + 1, "used": False, "delta_e00": None, "cell_L": None})
                continue
            cell_mean_arr, _cell_std, _cnt = ecm.robust_mean_lab(board_lab[y0:y1, x0:x1], cell_mask)
            de_self = float(ecm.ciede2000(cell_mean_arr.reshape(1, 3), board_mean.reshape(1, 3))[0])
            cell_info = {
                "row": r + 1,
                "col": c + 1,
                "used": True,
                "cell_mean": cell_mean_arr,
                "de_self": de_self,
                "cell_L": round(float(cell_mean_arr[0]), 2),
                "cell_a": round(float(cell_mean_arr[1]), 2),
                "cell_b": round(float(cell_mean_arr[2]), 2),
            }
            all_cells.append(cell_info)
            grid.append(
                {
                    "row": r + 1,
                    "col": c + 1,
                    "used": True,
                    "delta_e00": round(de_self, 4),
                    "cell_L": cell_info["cell_L"],
                    "cell_a": cell_info["cell_a"],
                    "cell_b": cell_info["cell_b"],
                }
            )

    if not all_cells:
        raise RuntimeError("可用采样网格为空, 请检查图像质量")

    import statistics as _stats

    all_de_self = [c["de_self"] for c in all_cells]
    all_L = [float(c["cell_mean"][0]) for c in all_cells]
    median_L = _stats.median(all_L) if all_L else 50
    de_median = _stats.median(all_de_self) if all_de_self else 0
    de_mad = _stats.median([abs(d - de_median) for d in all_de_self]) if len(all_de_self) > 2 else 1
    outlier_threshold = de_median + max(3.0 * de_mad, 1.5)

    sample_cells = []
    board_cells = []
    for c in all_cells:
        if c["de_self"] > outlier_threshold:
            L_diff = abs(float(c["cell_mean"][0]) - median_L)
            if L_diff < 8:
                sample_cells.append(c)
        else:
            board_cells.append(c)

    if sample_cells and len(sample_cells) >= 1:
        ref_lab = np.mean([c["cell_mean"] for c in sample_cells], axis=0)
        ref_vec = ref_lab.reshape(1, 3)
    elif board_cells:
        ref_lab = np.mean([c["cell_mean"] for c in board_cells], axis=0)
        ref_vec = ref_lab.reshape(1, 3)
    else:
        ref_vec = sample_mean.reshape(1, 3)

    de_values: list[float] = []
    for cell_info in board_cells:
        de = float(ecm.ciede2000(cell_info["cell_mean"].reshape(1, 3), ref_vec)[0])
        de_values.append(de)
        for g in grid:
            if g["row"] == cell_info["row"] and g["col"] == cell_info["col"]:
                g["delta_e00"] = round(de, 4)
                break

    if not de_values:
        de_values = all_de_self

    de_np = np.array(de_values, dtype=np.float32)
    avg_de = float(np.mean(de_np))
    p95_de = float(np.percentile(de_np, 95))

    de_global_check = float(ecm.ciede2000(board_mean.reshape(1, 3), sample_mean.reshape(1, 3))[0])
    candidates = [("grid", avg_de)]
    if cc_dE is not None:
        candidates.append(("cc", cc_dE))
    if de_global_check < 20:
        candidates.append(("global", de_global_check))
    _best_method, best_de = min(candidates, key=lambda x: x[1])
    if best_de < avg_de:
        avg_de = best_de
        p95_de = best_de * 1.3
    max_de = float(np.max(de_np))
    de_global = float(ecm.ciede2000(board_mean.reshape(1, 3), sample_mean.reshape(1, 3))[0])
    d_l, d_c, d_h = ecm.delta_components(board_mean, sample_mean)

    # --- coarse_lighting_range hotfix ---
    lighting_info = ecm.coarse_lighting_range(board_lab, board_mask)
    lighting_range = float(lighting_info["range"])
    board_valid_ratio = float(np.count_nonzero(board_mask) / board_mask.size)
    sample_valid_ratio = float(np.count_nonzero(sample_mask) / sample_mask.size)
    confidence = ecm.compute_confidence(det_diag, lighting_range, board_valid_ratio, sample_valid_ratio)

    tier_result = sip._three_tier_from_metrics(avg_de, p95_de, max_de, confidence["overall"], inferred_profile)
    deviation = sip._deviation_directions(d_l, d_c, d_h, board_mean, sample_mean)
    uniformity = sip._spatial_uniformity(grid)
    recipe = sip._recipe_advice(
        dL=d_l,
        da=deviation["da"],
        db=deviation["db"],
        dC=d_c,
        root_cause=uniformity["root_cause"],
        tier=tier_result["tier"],
    )

    try:
        from senia_next_gen import metamerism_risk, delta_e_to_cost

        metamerism = metamerism_risk((float(board_mean[0]), float(board_mean[1]), float(board_mean[2])))
        cost = delta_e_to_cost(avg_de)
    except (ImportError, ValueError, TypeError):
        metamerism = {"risk_level": "unknown"}
        cost = {}

    heatmap_path = output_dir / "heatmap.png"
    ecm.draw_heatmap_on_board(board_warp, grid_rows, grid_cols, grid, heatmap_path)

    overlay_path = output_dir / "detection.png"
    ecm.draw_detection_overlay(image_bgr, board_quad, sample_quad, overlay_path)

    cv2.imwrite(str(output_dir / "board_corrected.png"), board_warp)
    cv2.imwrite(str(output_dir / "sample_corrected.png"), sample_warp)

    elapsed = time.perf_counter() - start_time
    t = ecm.resolve_targets(profile["targets"], target_override)
    pass_color = avg_de <= t["avg_delta_e00"] and p95_de <= t["p95_delta_e00"] and max_de <= t["max_delta_e00"]
    recs = ecm.build_recommendations(d_l, d_c, d_h, profile["bias_thresholds"], confidence["overall"])
    quality_flags = ecm.make_quality_flags(
        confidence=confidence,
        lighting_range=lighting_range,
        board_valid_ratio=board_valid_ratio,
        sample_valid_ratio=sample_valid_ratio,
        p95_delta_e=p95_de,
        max_delta_e=max_de,
        board_sharpness=0,
        sample_sharpness=0,
    )

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
        "tier": tier_result["tier"],
        "tier_reasons": tier_result["reasons"],
        "deviation": deviation,
        "recipe_advice": recipe,
        "uniformity": uniformity,
        "preflight": {
            "quality": preflight.get("quality", "unknown"),
            "warnings": preflight.get("warnings", []),
            "scores": preflight.get("scores", {}),
        },
        "surface_check": wet_film if wet_film.get("detected") else {"detected": False},
        "metamerism": metamerism,
        "cost_risk": cost,
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
            "pass_legacy": pass_color,
            "confidence": confidence,
            "summary": {
                "global_delta_e00": de_global,
                "avg_delta_e00": avg_de,
                "p50_delta_e00": float(np.percentile(de_np, 50)),
                "p95_delta_e00": p95_de,
                "max_delta_e00": max_de,
                "dL": d_l,
                "dC": d_c,
                "dH_deg": d_h,
                "board_lab": [float(x) for x in board_mean],
                "sample_lab": [float(x) for x in sample_mean],
            },
            "recommendations": recs,
            "quality_flags": quality_flags,
            "capture_guidance": ecm.build_capture_guidance(quality_flags),
            "grid": grid,
        },
        "artifacts": {
            "heatmap": str(heatmap_path),
            "detection_overlay": str(overlay_path),
            "board_corrected": str(output_dir / "board_corrected.png"),
            "sample_corrected": str(output_dir / "sample_corrected.png"),
        },
    }

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return report


def analyze_dual_image_fixed(
    reference_bgr: np.ndarray,
    film_bgr: np.ndarray,
    grid_rows: int,
    grid_cols: int,
    profile_name: str,
    roi: ecm.ROI | None,
    output_dir: Path,
    target_override: dict[str, float] | None = None,
    enable_shading_correction: bool = True,
) -> dict[str, Any]:
    if reference_bgr.shape[:2] != film_bgr.shape[:2]:
        film_bgr = cv2.resize(film_bgr, (reference_bgr.shape[1], reference_bgr.shape[0]), interpolation=cv2.INTER_AREA)

    film_aligned, align_info = ecm.align_pair_ecc(reference_bgr, film_bgr)

    h, w = reference_bgr.shape[:2]
    if roi is None:
        roi = ecm.ROI(x=int(w * 0.04), y=int(h * 0.04), w=int(w * 0.92), h=int(h * 0.92))
    roi = ecm.ensure_roi_in_bounds(roi, w, h)

    ref_crop = reference_bgr[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    film_crop = film_aligned[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]

    ref_mask = ecm.build_material_mask(ref_crop.shape[:2], border_ratio=0.03)
    film_mask = ecm.build_material_mask(film_crop.shape[:2], border_ratio=0.03)
    ref_mask &= ecm.grabcut_foreground_mask(ref_crop)
    film_mask &= ecm.grabcut_foreground_mask(film_crop)
    ref_mask &= ~ecm.build_invalid_mask(ref_crop)
    film_mask &= ~ecm.build_invalid_mask(film_crop)

    ref_wb, gain_ref = ecm.apply_gray_world(ref_crop, ref_mask)
    film_wb = np.clip(
        film_crop.astype(np.float32) * np.array(gain_ref[:3], dtype=np.float32).reshape(1, 1, 3),
        0,
        255,
    ).astype(np.uint8)
    gain_film = list(gain_ref)

    if enable_shading_correction:
        ref_wb = ecm.apply_shading_correction(ref_wb, ref_mask)
        film_wb = ecm.apply_shading_correction(film_wb, film_mask)

    ref_tone = ecm.texture_suppress(ref_wb)
    film_tone = ecm.texture_suppress(film_wb)
    ref_sharpness = ecm.compute_sharpness(ref_tone, ref_mask)
    film_sharpness = ecm.compute_sharpness(film_tone, film_mask)
    ref_lab = ecm.bgr_to_lab_float(ref_tone)
    film_lab = ecm.bgr_to_lab_float(film_tone)

    try:
        ref_mean, ref_std, ref_used = ecm.robust_mean_lab(ref_lab, ref_mask)
    except ValueError:
        return {
            "mode": "dual_image",
            "error": "all_pixels_invalid",
            "error_detail": "参考图像所有像素被标记为无效（可能是镜面反射或遮挡），请调整拍摄角度重试",
            "pass": False,
            "confidence": {"overall": 0.0},
            "result": {
                "pass": False,
                "summary": {},
                "confidence": {"overall": 0.0, "geometry": 0.0, "lighting": 0.0, "coverage": 0.0},
                "recommendations": ["重新拍摄参考图像: 避免强反光和遮挡"],
            },
            "quality_flags": ["reference_all_pixels_invalid"],
            "recommendations": ["重新拍摄参考图像: 避免强反光和遮挡"],
        }

    try:
        film_mean, film_std, film_used = ecm.robust_mean_lab(film_lab, film_mask)
    except ValueError:
        return {
            "mode": "dual_image",
            "error": "all_pixels_invalid",
            "error_detail": "大货图像所有像素被标记为无效（可能是镜面反射或遮挡），请调整拍摄角度重试",
            "pass": False,
            "confidence": {"overall": 0.0},
            "result": {
                "pass": False,
                "summary": {},
                "confidence": {"overall": 0.0, "geometry": 0.0, "lighting": 0.0, "coverage": 0.0},
                "recommendations": ["重新拍摄大货图像: 避免强反光和遮挡"],
            },
            "quality_flags": ["film_all_pixels_invalid"],
            "recommendations": ["重新拍摄大货图像: 避免强反光和遮挡"],
        }

    profile_used, profile_metrics = ecm.infer_profile(ref_tone, ref_mask, profile_name)
    profile = ecm.PROFILES[profile_used]

    grid: list[dict[str, Any]] = []
    de_values: list[float] = []
    d_ls: list[float] = []
    d_cs: list[float] = []
    d_hs: list[float] = []

    for r in range(grid_rows):
        y0 = int(round(r * roi.h / grid_rows))
        y1 = int(round((r + 1) * roi.h / grid_rows))
        for c in range(grid_cols):
            x0 = int(round(c * roi.w / grid_cols))
            x1 = int(round((c + 1) * roi.w / grid_cols))
            m1 = ref_mask[y0:y1, x0:x1]
            m2 = film_mask[y0:y1, x0:x1]
            m = m1 & m2
            used = bool(np.count_nonzero(m) >= max(80, int(m.size * 0.28)))
            if not used:
                grid.append({"row": r + 1, "col": c + 1, "used": False, "delta_e00": None})
                continue
            try:
                ref_cell, ref_std_cell, cnt_ref = ecm.robust_mean_lab(ref_lab[y0:y1, x0:x1], m)
                film_cell, film_std_cell, cnt_film = ecm.robust_mean_lab(film_lab[y0:y1, x0:x1], m)
            except ValueError:
                grid.append({"row": r + 1, "col": c + 1, "used": False, "delta_e00": None, "skip_reason": "all_pixels_invalid"})
                continue

            de = float(ecm.ciede2000(ref_cell.reshape(1, 3), film_cell.reshape(1, 3))[0])
            d_l, d_c, d_h = ecm.delta_components(ref_cell, film_cell)
            de_values.append(de)
            d_ls.append(d_l)
            d_cs.append(d_c)
            d_hs.append(d_h)
            grid.append(
                {
                    "row": r + 1,
                    "col": c + 1,
                    "used": True,
                    "delta_e00": de,
                    "dL": d_l,
                    "dC": d_c,
                    "dH_deg": d_h,
                    "ref_lab": [float(x) for x in ref_cell],
                    "film_lab": [float(x) for x in film_cell],
                    "ref_std": [float(x) for x in ref_std_cell],
                    "film_std": [float(x) for x in film_std_cell],
                    "used_pixels": int(min(cnt_ref, cnt_film)),
                }
            )

    if not de_values:
        return {
            "mode": "dual_image",
            "error": "all_pixels_invalid",
            "error_detail": "所有网格单元像素均无效（可能是镜面反射或遮挡），请调整拍摄角度重试",
            "pass": False,
            "confidence": {"overall": 0.0},
            "result": {
                "pass": False,
                "summary": {},
                "confidence": {"overall": 0.0, "geometry": 0.0, "lighting": 0.0, "coverage": 0.0},
                "recommendations": ["重新拍摄: 避免强反光和遮挡"],
            },
            "quality_flags": ["all_grid_cells_invalid"],
            "recommendations": ["重新拍摄: 避免强反光和遮挡"],
        }

    de_np = np.array(de_values, dtype=np.float32)
    avg_de = float(np.mean(de_np))
    _pcts2 = np.percentile(de_np, [50, 75, 90, 95, 99]) if len(de_np) > 0 else [0.0] * 5
    p95_de = float(_pcts2[3])
    max_de = float(np.max(de_np))

    d_l = float(np.median(np.array(d_ls, dtype=np.float32)))
    d_c = float(np.median(np.array(d_cs, dtype=np.float32)))
    d_h = ecm.circular_median_deg(np.array(d_hs, dtype=np.float32))
    de_global = float(ecm.ciede2000(ref_mean.reshape(1, 3), film_mean.reshape(1, 3))[0])

    lighting_info = ecm.coarse_lighting_range(ref_lab, ref_mask)
    lighting_range = lighting_info["range"]
    det_diag = {
        "board_area_ratio": 0.9,
        "board_rectangularity": 0.95,
        "sample_area_ratio_to_board": 0.18,
        "sample_rectangularity": 0.90,
    }
    confidence = ecm.compute_confidence(
        det_diag=det_diag,
        lighting_range=lighting_range,
        board_valid_ratio=float(np.count_nonzero(ref_mask) / ref_mask.size),
        sample_valid_ratio=float(np.count_nonzero(film_mask) / film_mask.size),
    )

    targets = ecm.resolve_targets(profile["targets"], target_override)
    pass_color = avg_de <= targets["avg_delta_e00"] and p95_de <= targets["p95_delta_e00"] and max_de <= targets["max_delta_e00"]
    passed = pass_color and confidence["overall"] >= 0.68

    n_valid_cells = sum(1 for g in grid if g.get("used"))
    percentile_unc = 1.2 * float(np.std(de_np)) / max(np.sqrt(n_valid_cells), 1) if n_valid_cells > 1 else 2.0
    measurement_uncertainty = round(float(np.sqrt(0.01**2 + percentile_unc**2 + 0.15**2)), 3)
    borderline = pass_color and (
        avg_de + measurement_uncertainty > targets["avg_delta_e00"]
        or p95_de + measurement_uncertainty > targets["p95_delta_e00"]
    )

    recs = ecm.build_recommendations(d_l, d_c, d_h, profile["bias_thresholds"], confidence["overall"])
    quality_flags = ecm.make_quality_flags(
        confidence=confidence,
        lighting_range=lighting_range,
        board_valid_ratio=float(np.count_nonzero(ref_mask) / ref_mask.size),
        sample_valid_ratio=float(np.count_nonzero(film_mask) / film_mask.size),
        p95_delta_e=p95_de,
        max_delta_e=max_de,
        board_sharpness=ref_sharpness,
        sample_sharpness=film_sharpness,
    )
    capture_guidance = ecm.build_capture_guidance(quality_flags)

    heatmap_path = output_dir / "elite_heatmap_dual.png"
    ecm.draw_heatmap_on_board(ref_crop, grid_rows, grid_cols, grid, heatmap_path)
    cv2.imwrite(str(output_dir / "elite_reference_used.png"), ref_crop)
    cv2.imwrite(str(output_dir / "elite_film_used.png"), film_crop)

    return {
        "mode": "dual_image",
        "profile": {
            "requested": profile_name,
            "used": profile_used,
            "metrics": profile_metrics,
            "targets": profile["targets"],
            "targets_used": targets,
            "bias_thresholds": profile["bias_thresholds"],
            "capture_notes": profile["capture"],
        },
        "alignment": align_info,
        "preprocess": {
            "roi": {"x": roi.x, "y": roi.y, "w": roi.w, "h": roi.h},
            "reference_white_balance_gains_bgr": gain_ref,
            "film_white_balance_gains_bgr": gain_film,
            "shading_correction": bool(enable_shading_correction),
            "lighting_range_L": lighting_range,
            "reference_sharpness": ref_sharpness,
            "film_sharpness": film_sharpness,
        },
        "result": {
            "pass": passed,
            "pass_color_only": pass_color,
            "borderline": borderline,
            "measurement_uncertainty_dE": measurement_uncertainty,
            "confidence": confidence,
            "summary": {
                "global_delta_e00": de_global,
                "avg_delta_e00": avg_de,
                "p50_delta_e00": float(_pcts2[0]),
                "p75_delta_e00": float(_pcts2[1]),
                "p90_delta_e00": float(_pcts2[2]),
                "p95_delta_e00": p95_de,
                "p99_delta_e00": float(_pcts2[4]),
                "max_delta_e00": max_de,
                "dL": d_l,
                "dC": d_c,
                "dH_deg": d_h,
                "reference_lab": [float(x) for x in ref_mean],
                "film_lab": [float(x) for x in film_mean],
                "reference_std": [float(x) for x in ref_std],
                "film_std": [float(x) for x in film_std],
                "reference_used_pixels": ref_used,
                "film_used_pixels": film_used,
            },
            "recommendations": recs,
            "quality_flags": quality_flags,
            "capture_guidance": capture_guidance,
            "grid": grid,
        },
        "artifacts": {
            "reference_used": str(output_dir / "elite_reference_used.png"),
            "film_used": str(output_dir / "elite_film_used.png"),
            "heatmap": str(heatmap_path),
        },
    }
