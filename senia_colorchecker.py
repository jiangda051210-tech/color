"""
SENIA ColorChecker 自动检测 + CCM 提取
======================================
从照片中自动找到 X-Rite ColorChecker 色卡,
提取 24 色块实测 RGB, 拟合 3×3 CCM.

流程:
  1. 在照片中检测色卡 (基于颜色聚类 + 网格结构)
  2. 定位 24 色块中心点
  3. 提取每个色块的平均 RGB
  4. 调用 senia_calibration.fit_ccm_least_squares() 拟合 CCM
  5. 返回 CCM + 质量评估
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from senia_calibration import (
    COLORCHECKER_LAB_D50,
    COLORCHECKER_SRGB_D65,
    CalibrationResult,
    fit_ccm_least_squares,
)


def detect_colorchecker(
    image_bgr: np.ndarray,
    min_area_ratio: float = 0.003,
    max_area_ratio: float = 0.15,
) -> dict[str, Any]:
    """
    从照片中自动检测 ColorChecker 色卡.

    返回:
      found: bool
      quad: 4点坐标 (如果检测到)
      patches_rgb: 24色块 RGB 列表
      ccm_result: CalibrationResult
    """
    h, w = image_bgr.shape[:2]
    image_area = h * w

    # Step 1: 找到可能是色卡的矩形区域
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        ratio = area / image_area
        if ratio < min_area_ratio or ratio > max_area_ratio:
            continue
        rect = cv2.minAreaRect(cnt)
        rw, rh = rect[1]
        if rw < 20 or rh < 20:
            continue
        rect_area = rw * rh
        if rect_area < 1:
            continue
        rectangularity = area / rect_area
        if rectangularity < 0.6:
            continue
        # ColorChecker 长宽比约 4:6 ≈ 0.67 (或 1.5)
        aspect = max(rw, rh) / (min(rw, rh) + 1e-6)
        if 1.2 <= aspect <= 2.0:
            candidates.append({
                "contour": cnt,
                "rect": rect,
                "area": area,
                "rectangularity": rectangularity,
                "aspect": aspect,
                "score": rectangularity * (1.0 - abs(aspect - 1.5) / 1.5),
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)

    if not candidates:
        return {"found": False, "reason": "no_colorchecker_candidate"}

    # Step 2: 对最佳候选区域做透视校正
    best = candidates[0]
    box = cv2.boxPoints(best["rect"]).astype(np.float32)
    box = _order_quad(box)

    rw, rh = best["rect"][1]
    if rw < rh:
        rw, rh = rh, rw
    dst_w, dst_h = int(rw), int(rh)
    # 确保宽>高 (色卡横放)
    if dst_w < dst_h:
        dst_w, dst_h = dst_h, dst_w

    dst = np.array([[0, 0], [dst_w, 0], [dst_w, dst_h], [0, dst_h]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(box, dst)
    warped = cv2.warpPerspective(image_bgr, M, (dst_w, dst_h))

    # Step 3: 从校正后的色卡图中提取 4×6 = 24 色块
    patches_rgb = _extract_24_patches(warped)
    if patches_rgb is None or len(patches_rgb) < 24:
        # 尝试转置 (色卡可能竖放)
        warped_rot = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
        patches_rgb = _extract_24_patches(warped_rot)
        if patches_rgb is None or len(patches_rgb) < 24:
            return {
                "found": True,
                "quad": box.tolist(),
                "reason": "colorchecker_detected_but_patches_extraction_failed",
                "candidate_count": len(candidates),
            }

    # Step 4: 拟合 CCM
    measured_rgb = [(int(r), int(g), int(b)) for r, g, b in patches_rgb]
    try:
        ccm_result = fit_ccm_least_squares(measured_rgb)
    except ValueError as e:
        return {
            "found": True,
            "quad": box.tolist(),
            "patches_rgb": [list(p) for p in measured_rgb],
            "reason": f"ccm_fit_failed: {e}",
        }

    return {
        "found": True,
        "quad": box.tolist(),
        "patches_rgb": [list(p) for p in measured_rgb],
        "ccm": ccm_result.ccm,
        "ccm_rmse": ccm_result.rmse,
        "ccm_max_error": ccm_result.max_error,
        "ccm_quality": ccm_result.quality,
        "patch_errors": ccm_result.patch_errors,
    }


def _extract_24_patches(
    card_bgr: np.ndarray,
    rows: int = 4,
    cols: int = 6,
    margin: float = 0.08,
    patch_size_ratio: float = 0.4,
) -> list[tuple[int, int, int]] | None:
    """
    从校正后的色卡图中提取 24 色块的平均 RGB.
    假设色卡为 4行×6列排列.
    """
    h, w = card_bgr.shape[:2]
    if h < 60 or w < 90:
        return None  # Too small for reliable patch extraction

    cell_h = h / rows
    cell_w = w / cols
    patch_h = int(cell_h * patch_size_ratio)
    patch_w = int(cell_w * patch_size_ratio)

    patches = []
    for r in range(rows):
        cy = int((r + 0.5) * cell_h)
        for c in range(cols):
            cx = int((c + 0.5) * cell_w)
            y0 = max(0, cy - patch_h // 2)
            y1 = min(h, cy + patch_h // 2)
            x0 = max(0, cx - patch_w // 2)
            x1 = min(w, cx + patch_w // 2)
            patch = card_bgr[y0:y1, x0:x1]
            if patch.size == 0:
                return None  # Empty patch region → extraction failed
            mean_bgr = patch.mean(axis=(0, 1))
            patches.append((int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])))

    return patches


def _order_quad(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([
        pts[np.argmin(s)],
        pts[np.argmin(d)],
        pts[np.argmax(s)],
        pts[np.argmax(d)],
    ], dtype=np.float32)


def calibrate_from_photo(
    image_bgr: np.ndarray,
) -> dict[str, Any]:
    """
    一键校准: 从照片自动检测色卡 → 提取色块 → 拟合CCM.

    返回包含 ccm 矩阵和质量评估的 dict.
    如果检测失败, 返回 found=False 和原因.
    """
    return detect_colorchecker(image_bgr)
