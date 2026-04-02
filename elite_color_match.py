
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from elite_decision_center import attach_decision_center
from elite_quality_history import assess_current_vs_history, init_db, record_run, recommend_policy_adjustments
from elite_process_advisor import attach_process_advice


@dataclass
class ROI:
    x: int
    y: int
    w: int
    h: int


@dataclass
class RectCandidate:
    quad: np.ndarray
    area: float
    rect_area: float
    rectangularity: float
    center: tuple[float, float]


PROFILES: dict[str, dict[str, Any]] = {
    "solid": {
        "targets": {"avg_delta_e00": 1.0, "p95_delta_e00": 1.8, "max_delta_e00": 2.5},
        "bias_thresholds": {"dL": 0.30, "dC": 0.30, "dH_deg": 1.8},
        "capture": "适用于纯色、低纹理材料，阈值最严格。",
    },
    "wood": {
        "targets": {"avg_delta_e00": 1.8, "p95_delta_e00": 2.8, "max_delta_e00": 4.0},
        "bias_thresholds": {"dL": 0.40, "dC": 0.45, "dH_deg": 2.5},
        "capture": "适用于木纹等中高纹理材料，采用纹理抑制与稳健统计。",
    },
    "stone": {
        "targets": {"avg_delta_e00": 2.1, "p95_delta_e00": 3.2, "max_delta_e00": 4.5},
        "bias_thresholds": {"dL": 0.45, "dC": 0.50, "dH_deg": 3.0},
        "capture": "适用于石纹、强纹理材料，重点看大面积综合色调一致性。",
    },
    "metallic": {
        "targets": {"avg_delta_e00": 1.6, "p95_delta_e00": 2.6, "max_delta_e00": 3.8},
        "bias_thresholds": {"dL": 0.35, "dC": 0.40, "dH_deg": 2.2},
        "capture": "适用于金属/珠光，需要偏振光或固定入射角降低镜面反射。",
    },
    "high_gloss": {
        "targets": {"avg_delta_e00": 1.4, "p95_delta_e00": 2.2, "max_delta_e00": 3.0},
        "bias_thresholds": {"dL": 0.30, "dC": 0.35, "dH_deg": 2.0},
        "capture": "适用于高光材质，要求强控光环境并抑制高光区影响。",
    },
}


def parse_grid(text: str) -> tuple[int, int]:
    parts = text.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("grid must be like 6x8")
    rows, cols = map(int, parts)
    if rows <= 0 or cols <= 0:
        raise argparse.ArgumentTypeError("rows/cols must be > 0")
    return rows, cols


def parse_roi(text: str) -> ROI:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    x, y, w, h = map(int, parts)
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("ROI width and height must be > 0")
    return ROI(x=x, y=y, w=w, h=h)


def parse_quad(text: str) -> np.ndarray:
    # Format: x1,y1;x2,y2;x3,y3;x4,y4
    pairs = [p.strip() for p in text.split(";") if p.strip()]
    if len(pairs) != 4:
        raise argparse.ArgumentTypeError("Quad must be x1,y1;x2,y2;x3,y3;x4,y4")
    pts: list[list[float]] = []
    for pair in pairs:
        xy = [v.strip() for v in pair.split(",")]
        if len(xy) != 2:
            raise argparse.ArgumentTypeError("Quad point must be x,y")
        x, y = map(float, xy)
        pts.append([x, y])
    return np.array(pts, dtype=np.float32)


def parse_int_list(text: str) -> list[int]:
    items = [x.strip() for x in text.split(",") if x.strip()]
    if not items:
        raise argparse.ArgumentTypeError("Expected comma-separated integers")
    try:
        return [int(x) for x in items]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected comma-separated integers") from exc


def parse_path_list(text: str) -> list[Path]:
    items = [x.strip() for x in text.split(",") if x.strip()]
    if not items:
        raise argparse.ArgumentTypeError("Expected comma-separated file paths")
    return [Path(x) for x in items]


def roi_to_quad(roi: ROI) -> np.ndarray:
    x0, y0 = float(roi.x), float(roi.y)
    x1 = float(roi.x + roi.w)
    y1 = float(roi.y + roi.h)
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)


def apply_profile_config(config_path: Path) -> dict[str, Any]:
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    payload = raw["profiles"] if isinstance(raw, dict) and "profiles" in raw else raw
    if not isinstance(payload, dict):
        raise ValueError("profile config must be a JSON object")

    applied: dict[str, Any] = {}
    for profile_name, update in payload.items():
        if not isinstance(update, dict):
            continue
        if profile_name not in PROFILES:
            continue
        profile = PROFILES[profile_name]
        if "targets" in update and isinstance(update["targets"], dict):
            for key in ("avg_delta_e00", "p95_delta_e00", "max_delta_e00"):
                if key in update["targets"]:
                    profile["targets"][key] = float(update["targets"][key])
        if "bias_thresholds" in update and isinstance(update["bias_thresholds"], dict):
            for key in ("dL", "dC", "dH_deg"):
                if key in update["bias_thresholds"]:
                    profile["bias_thresholds"][key] = float(update["bias_thresholds"][key])
        if "capture" in update and isinstance(update["capture"], str):
            profile["capture"] = update["capture"]
        applied[profile_name] = profile
    return applied


def ensure_roi_in_bounds(roi: ROI, width: int, height: int) -> ROI:
    x = max(0, min(roi.x, width - 1))
    y = max(0, min(roi.y, height - 1))
    w = min(roi.w, width - x)
    h = min(roi.h, height - y)
    if w <= 0 or h <= 0:
        raise ValueError("ROI is out of image bounds")
    return ROI(x=x, y=y, w=w, h=h)


def read_image(path: Path) -> np.ndarray:
    # Prefer imdecode to support Unicode paths and avoid OpenCV warning noise.
    image = None
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size > 0:
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    return image


def order_quad(points: np.ndarray) -> np.ndarray:
    pts = points.astype(np.float32)
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def warp_quad(image: np.ndarray, quad: np.ndarray, target_long_side: int = 1400) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rect = order_quad(quad)
    tl, tr, br, bl = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)

    base_w = max(2, int(round(max(width_a, width_b))))
    base_h = max(2, int(round(max(height_a, height_b))))

    scale = min(1.0, target_long_side / max(base_w, base_h))
    new_w = max(2, int(round(base_w * scale)))
    new_h = max(2, int(round(base_h * scale)))

    dst = np.array(
        [[0, 0], [new_w - 1, 0], [new_w - 1, new_h - 1], [0, new_h - 1]],
        dtype=np.float32,
    )
    m = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, m, (new_w, new_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return warped, m, rect


def bgr_to_lab_float(image_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = np.empty_like(lab)
    out[..., 0] = lab[..., 0] * (100.0 / 255.0)
    out[..., 1] = lab[..., 1] - 128.0
    out[..., 2] = lab[..., 2] - 128.0
    return out


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    l1, a1, b1 = lab1[:, 0], lab1[:, 1], lab1[:, 2]
    l2, a2, b2 = lab2[:, 0], lab2[:, 1], lab2[:, 2]

    c1 = np.sqrt(a1**2 + b1**2)
    c2 = np.sqrt(a2**2 + b2**2)
    avg_c = (c1 + c2) / 2.0

    g = 0.5 * (1.0 - np.sqrt((avg_c**7) / (avg_c**7 + 25.0**7 + 1e-12)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.sqrt(a1p**2 + b1**2)
    c2p = np.sqrt(a2p**2 + b2**2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dl = l2 - l1
    dc = c2p - c1p

    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, dh)
    dh = np.where(dh < -180.0, dh + 360.0, dh)
    dh = np.where((c1p * c2p) == 0, 0.0, dh)
    dhp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2.0))

    avg_l = (l1 + l2) / 2.0
    avg_cp = (c1p + c2p) / 2.0

    hp_sum = h1p + h2p
    avg_hp = np.where(np.abs(h1p - h2p) > 180.0, (hp_sum + 360.0) / 2.0, hp_sum / 2.0)
    avg_hp = np.where((c1p * c2p) == 0, hp_sum, avg_hp)

    t = (
        1.0
        - 0.17 * np.cos(np.radians(avg_hp - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * avg_hp))
        + 0.32 * np.cos(np.radians(3.0 * avg_hp + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * avg_hp - 63.0))
    )

    delta_theta = 30.0 * np.exp(-(((avg_hp - 275.0) / 25.0) ** 2))
    rc = 2.0 * np.sqrt((avg_cp**7) / (avg_cp**7 + 25.0**7 + 1e-12))
    sl = 1.0 + (0.015 * ((avg_l - 50.0) ** 2)) / np.sqrt(20.0 + ((avg_l - 50.0) ** 2))
    sc = 1.0 + 0.045 * avg_cp
    sh = 1.0 + 0.015 * avg_cp * t
    rt = -np.sin(np.radians(2.0 * delta_theta)) * rc

    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhp / sh) ** 2 + rt * (dc / sc) * (dhp / sh))


def circular_median_deg(deg_values: np.ndarray) -> float:
    radians = np.deg2rad(deg_values)
    sin_mean = np.mean(np.sin(radians))
    cos_mean = np.mean(np.cos(radians))
    return float(np.rad2deg(np.arctan2(sin_mean, cos_mean)))


def robust_mean_lab(lab: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    vals = lab[mask]
    if vals.size == 0:
        raise ValueError("No valid pixels for LAB statistics")

    l_low, l_high = np.percentile(vals[:, 0], [4, 96])
    a_low, a_high = np.percentile(vals[:, 1], [2, 98])
    b_low, b_high = np.percentile(vals[:, 2], [2, 98])
    keep = (
        (vals[:, 0] >= l_low)
        & (vals[:, 0] <= l_high)
        & (vals[:, 1] >= a_low)
        & (vals[:, 1] <= a_high)
        & (vals[:, 2] >= b_low)
        & (vals[:, 2] <= b_high)
    )

    filtered = vals[keep]
    if len(filtered) < max(60, int(len(vals) * 0.15)):
        filtered = vals

    return filtered.mean(axis=0), filtered.std(axis=0), int(len(filtered))


def apply_gray_world(image_bgr: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, list[float]]:
    valid = image_bgr[mask]
    if valid.size == 0:
        means = image_bgr.reshape(-1, 3).mean(axis=0)
    else:
        means = valid.reshape(-1, 3).mean(axis=0)
    gray = float(np.mean(means))
    gains = gray / np.maximum(means, 1e-6)
    balanced = np.clip(image_bgr.astype(np.float32) * gains.reshape(1, 1, 3), 0, 255).astype(np.uint8)
    return balanced, gains.tolist()


def texture_suppress(image_bgr: np.ndarray) -> np.ndarray:
    """
    纹理抑制: 消除木纹/石纹细节, 提取底色.
    对地板装饰膜特别重要 — 对色比的是底色不是纹理.

    双重滤波: 先双边保边缘, 再中值去残余纹理.
    """
    # 第一轮: 强力双边滤波 (d=15, 比原来d=9更强)
    filtered = cv2.bilateralFilter(image_bgr, d=15, sigmaColor=60, sigmaSpace=15)
    # 第二轮: 中值滤波去残余纹理颗粒
    filtered = cv2.medianBlur(filtered, 5)
    return filtered


def apply_shading_correction(image_bgr: np.ndarray, mask: np.ndarray, strength: float = 0.65) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    sigma = max(8.0, min(h, w) * 0.08)
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    l = lab[..., 0]
    illum = cv2.GaussianBlur(l, (0, 0), sigmaX=sigma, sigmaY=sigma)
    if np.count_nonzero(mask) > 100:
        ref = float(np.median(illum[mask]))
    else:
        ref = float(np.median(illum))
    gain = ref / np.maximum(illum, 1e-3)
    gain = np.clip(gain, 0.75, 1.25)
    mix_gain = 1.0 + strength * (gain - 1.0)
    lab[..., 0] = np.clip(l * mix_gain, 0, 255)
    out = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    return out


def build_invalid_mask(image_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lab = bgr_to_lab_float(image_bgr)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)

    dark = gray < np.percentile(gray, 6)
    text_like = blackhat > np.percentile(blackhat, 90)
    highlight = (hsv[..., 2] > 245) & (hsv[..., 1] < 38)

    med = np.median(lab.reshape(-1, 3), axis=0)
    mad = np.median(np.abs(lab.reshape(-1, 3) - med), axis=0) + 1e-5
    z = np.abs((lab - med) / mad)
    color_outlier = (z[..., 1] > 7.5) | (z[..., 2] > 7.5)

    invalid = (dark & text_like) | highlight | color_outlier
    invalid = cv2.morphologyEx(invalid.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    invalid = cv2.dilate(invalid, np.ones((3, 3), np.uint8), iterations=1)
    return invalid.astype(bool)


def build_material_mask(shape: tuple[int, int], border_ratio: float = 0.04) -> np.ndarray:
    h, w = shape
    mask = np.ones((h, w), dtype=bool)
    bx = int(w * border_ratio)
    by = int(h * border_ratio)
    mask[:by, :] = False
    mask[-by:, :] = False
    mask[:, :bx] = False
    mask[:, -bx:] = False
    return mask


def grabcut_foreground_mask(image_bgr: np.ndarray) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    rect = (int(w * 0.04), int(h * 0.06), int(w * 0.92), int(h * 0.88))
    mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(image_bgr, mask, rect, bgd, fgd, 4, cv2.GC_INIT_WITH_RECT)
        fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
        if np.mean(fg) > 0.20:
            return fg.astype(bool)
    except cv2.error:
        pass
    return np.ones((h, w), dtype=bool)

def contour_candidates(image_bgr: np.ndarray) -> list[RectCandidate]:
    """
    检测图像中的矩形区域 (大货/标样).

    针对木纹/石纹地板膜优化:
      1. 强力双边滤波消除纹理细节, 只保留板子与背景的边界
      2. 多尺度边缘检测 (粗+细两轮)
      3. 大核形态学闭合, 桥接因纹理断开的边缘
      4. 面积+矩形度双重过滤
    """
    h, w = image_bgr.shape[:2]
    image_area = h * w

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # 轻度模糊: 只消除噪点, 保留板子/标样边缘 (包括标样和大货之间的边界)
    smooth = cv2.GaussianBlur(gray, (5, 5), 0)

    # 多尺度边缘检测: 粗 (找板子外边界) + 细 (找标样边界)
    edge_coarse = cv2.Canny(smooth, 30, 100)
    edge_fine = cv2.Canny(gray, 40, 120)  # 用原始灰度, 更敏感
    thr = cv2.adaptiveThreshold(smooth, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 41, 8)

    combined = cv2.bitwise_or(edge_coarse, cv2.bitwise_or(edge_fine, thr))
    # 形态学闭合桥接断边, 但核不要太大 (否则标样边界被闭合掉)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    # RETR_TREE: 检测嵌套轮廓 (标样在大货上面 → 子轮廓)
    contours, hierarchy = cv2.findContours(combined, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    results: list[RectCandidate] = []

    for idx, cnt in enumerate(contours):
        area = float(cv2.contourArea(cnt))
        if area < image_area * 0.003:
            continue

        rect = cv2.minAreaRect(cnt)
        rw, rh = rect[1]
        if rw < 25 or rh < 25:
            continue
        rect_area = float(rw * rh)
        if rect_area <= 0:
            continue

        rectangularity = float(np.clip(area / rect_area, 0.0, 1.0))
        # 地板膜矩形度要求: 降低到 0.45 (大板子可能有轻微弯曲)
        if rectangularity < 0.40:
            continue

        box = cv2.boxPoints(rect).astype(np.float32)
        center = (float(rect[0][0]), float(rect[0][1]))
        results.append(RectCandidate(quad=box, area=area, rect_area=rect_area,
                                     rectangularity=rectangularity, center=center))

    results.sort(key=lambda c: c.rect_area, reverse=True)
    return results


def _find_sample_inside_board(image_bgr: np.ndarray, board_quad: np.ndarray) -> RectCandidate | None:
    """
    二次检测: 在 board 区域内部找 sample.

    策略 (按优先级):
      A. 局部颜色差异检测: 标样和大货虽然相似但不完全一样,
         用滑动窗口找"局部平均色和全局平均色最不一样"的矩形区域
      B. 边缘+阴影检测: 标样放在大货上会有微小投影/厚度差
      C. 高对比度文字/贴纸附近区域: 手写字通常写在标样上
    """
    h, w = image_bgr.shape[:2]
    quad = order_quad(board_quad)
    widths = [np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3])]
    heights = [np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])]
    bw, bh = int(max(widths)), int(max(heights))
    if bw < 100 or bh < 100:
        return None
    dst = np.array([[0, 0], [bw, 0], [bw, bh], [0, bh]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad, dst)
    warped = cv2.warpPerspective(image_bgr, M, (bw, bh))
    board_area = float(bw * bh)

    # === 策略 A: 局部颜色差异 (最可靠) ===
    # 把 board 分成粗网格, 找颜色和全局均值偏差最大的矩形区域
    lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 0] *= (100.0 / 255.0)
    lab[..., 1] -= 128.0
    lab[..., 2] -= 128.0

    global_mean = lab.reshape(-1, 3).mean(axis=0)

    # 滑动窗口搜索: 不同尺寸的矩形
    best: RectCandidate | None = None
    best_diff = -1.0

    for scale_h in [0.15, 0.20, 0.25, 0.30]:
        for scale_w in [0.20, 0.30, 0.40]:
            win_h = int(bh * scale_h)
            win_w = int(bw * scale_w)
            if win_h < 40 or win_w < 40:
                continue
            step_h = max(win_h // 3, 10)
            step_w = max(win_w // 3, 10)

            for y in range(0, bh - win_h, step_h):
                for x in range(0, bw - win_w, step_w):
                    region = lab[y:y + win_h, x:x + win_w]
                    region_mean = region.reshape(-1, 3).mean(axis=0)
                    diff = float(np.sqrt(np.sum((region_mean - global_mean) ** 2)))

                    area_ratio = (win_h * win_w) / board_area
                    if not (0.02 <= area_ratio <= 0.45):
                        continue

                    # 标样区域的颜色应该比全局均值有可检测的差异
                    if diff > best_diff and diff > 0.8:
                        best_diff = diff
                        box_warp = np.array([
                            [x, y], [x + win_w, y],
                            [x + win_w, y + win_h], [x, y + win_h]
                        ], dtype=np.float32)
                        M_inv = cv2.getPerspectiveTransform(dst, quad)
                        box_orig = cv2.perspectiveTransform(
                            box_warp.reshape(1, -1, 2), M_inv
                        ).reshape(-1, 2)
                        center = box_orig.mean(axis=0)
                        best = RectCandidate(
                            quad=box_orig.astype(np.float32),
                            area=float(win_h * win_w) * (h * w / board_area),
                            rect_area=float(win_h * win_w) * (h * w / board_area),
                            rectangularity=0.95,
                            center=(float(center[0]), float(center[1])),
                        )

    # === 策略 B: 边缘检测 (备选) ===
    if best is None:
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(gray, cv2.CV_16S, ksize=3)
        sharp = cv2.convertScaleAbs(sharp)
        edges = cv2.Canny(gray, 15, 50)
        edges = cv2.bitwise_or(edges, sharp)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=3)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        best_score = -1.0
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            ratio = area / board_area
            if not (0.02 <= ratio <= 0.45):
                continue
            rect = cv2.minAreaRect(cnt)
            rw2, rh2 = rect[1]
            if rw2 < 30 or rh2 < 30:
                continue
            rect_area = float(rw2 * rh2)
            if rect_area <= 0:
                continue
            rectangularity = float(np.clip(area / rect_area, 0.0, 1.0))
            if rectangularity < 0.45:
                continue
            score = area * rectangularity
            if score > best_score:
                best_score = score
                box = cv2.boxPoints(rect).astype(np.float32)
                M_inv = cv2.getPerspectiveTransform(dst, quad)
                box_orig = cv2.perspectiveTransform(box.reshape(1, -1, 2), M_inv).reshape(-1, 2)
                center = box_orig.mean(axis=0)
                best = RectCandidate(
                    quad=box_orig.astype(np.float32),
                    area=area * (h * w / board_area),
                    rect_area=rect_area * (h * w / board_area),
                    rectangularity=rectangularity,
                    center=(float(center[0]), float(center[1])),
                )
    return best


def choose_board_and_sample(cands: list[RectCandidate], image_shape: tuple[int, int, int],
                            image_bgr: np.ndarray | None = None) -> tuple[RectCandidate | None, RectCandidate | None, dict[str, Any]]:
    h, w = image_shape[:2]
    image_area = float(h * w)

    board = None
    for c in cands:
        ratio = c.rect_area / image_area
        if 0.14 <= ratio <= 0.98 and c.rectangularity >= 0.52:
            board = c
            break

    if board is None and cands:
        board = cands[0]

    sample = None
    if board is not None:
        board_poly = order_quad(board.quad).reshape(-1, 1, 2)
        best_score = -1.0
        for c in cands:
            if c is board:
                continue
            rel = c.rect_area / max(board.rect_area, 1.0)
            if not (0.015 <= rel <= 0.50):
                continue
            inside = cv2.pointPolygonTest(board_poly, c.center, measureDist=False) >= 0
            if not inside:
                continue
            score = c.rect_area * (0.45 + 0.55 * c.rectangularity)
            if score > best_score:
                best_score = score
                sample = c

    # 二次检测: 如果主检测没找到标样, 用更敏感的方法在 board 内部找
    if sample is None and board is not None and image_bgr is not None:
        sample = _find_sample_inside_board(image_bgr, board.quad)

    diag = {
        "candidates": len(cands),
        "board_area_ratio": float(board.rect_area / image_area) if board is not None else 0.0,
        "board_rectangularity": float(board.rectangularity) if board is not None else 0.0,
        "sample_area_ratio_to_board": float(sample.rect_area / board.rect_area) if (board is not None and sample is not None) else 0.0,
        "sample_rectangularity": float(sample.rectangularity) if sample is not None else 0.0,
        "sample_detection_method": "secondary" if (sample is not None and id(sample) not in {id(c) for c in cands}) else "primary",
    }
    return board, sample, diag


def infer_profile(board_bgr: np.ndarray, board_mask: np.ndarray, requested_profile: str) -> tuple[str, dict[str, float]]:
    if requested_profile != "auto":
        return requested_profile, {"texture_score": 0.0, "highlight_ratio": 0.0, "note": "manual profile"}

    gray = cv2.cvtColor(board_bgr, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(grad_x**2 + grad_y**2)

    valid = board_mask
    if np.count_nonzero(valid) < 100:
        valid = np.ones_like(board_mask, dtype=bool)

    texture_score = float(np.percentile(grad[valid], 75))
    hsv = cv2.cvtColor(board_bgr, cv2.COLOR_BGR2HSV)
    highlight_ratio = float(np.mean((hsv[..., 2] > 244) & (hsv[..., 1] < 35) & valid))

    if highlight_ratio > 0.05:
        name = "high_gloss"
    elif texture_score > 22:
        name = "stone"
    elif texture_score > 9.5:
        name = "wood"
    else:
        name = "solid"

    return name, {"texture_score": texture_score, "highlight_ratio": highlight_ratio, "note": "auto-inferred"}


def delta_components(reference_lab: np.ndarray, target_lab: np.ndarray) -> tuple[float, float, float]:
    d_l = float(target_lab[0] - reference_lab[0])

    c_ref = float(np.hypot(reference_lab[1], reference_lab[2]))
    c_tar = float(np.hypot(target_lab[1], target_lab[2]))
    d_c = c_tar - c_ref

    h_ref = float(np.degrees(np.arctan2(reference_lab[2], reference_lab[1])))
    h_tar = float(np.degrees(np.arctan2(target_lab[2], target_lab[1])))
    d_h = (h_tar - h_ref + 180.0) % 360.0 - 180.0
    return d_l, d_c, d_h


def build_recommendations(d_l: float, d_c: float, d_h: float, thresholds: dict[str, float], confidence: float) -> list[str]:
    recs: list[str] = []

    if d_l > thresholds["dL"]:
        recs.append(f"偏亮（dL={d_l:.2f}），建议降低明度或总墨量 1%-3%。")
    elif d_l < -thresholds["dL"]:
        recs.append(f"偏暗（dL={d_l:.2f}），建议提高明度或总墨量 1%-3%。")

    if d_c > thresholds["dC"]:
        recs.append(f"偏艳（dC={d_c:.2f}），建议降低彩度通道 1%-2%。")
    elif d_c < -thresholds["dC"]:
        recs.append(f"偏灰（dC={d_c:.2f}），建议提高彩度通道 1%-2%。")

    if abs(d_h) > thresholds["dH_deg"]:
        direction = "逆时针" if d_h > 0 else "顺时针"
        recs.append(f"色相偏移（dH={d_h:.1f}°），建议 {direction} 微调色相通道 0.5%-1%。")

    if confidence < 0.72:
        recs.append("当前置信度偏低，建议重拍：镜头垂直、固定距离、避免阴影与高光。")

    if not recs:
        recs.append("综合色差稳定在阈值内，可维持当前工艺参数。")

    return recs


def de_color(value: float) -> tuple[int, int, int]:
    stops = [
        (0.0, np.array([46, 204, 113], dtype=np.float32)),
        (1.0, np.array([15, 196, 241], dtype=np.float32)),
        (2.0, np.array([18, 156, 243], dtype=np.float32)),
        (3.0, np.array([60, 76, 231], dtype=np.float32)),
        (5.0, np.array([43, 57, 192], dtype=np.float32)),
    ]
    v = float(np.clip(value, 0.0, 5.0))
    for i in range(len(stops) - 1):
        x0, c0 = stops[i]
        x1, c1 = stops[i + 1]
        if x0 <= v <= x1:
            t = (v - x0) / (x1 - x0 + 1e-9)
            out = c0 * (1.0 - t) + c1 * t
            return int(out[0]), int(out[1]), int(out[2])
    last = stops[-1][1]
    return int(last[0]), int(last[1]), int(last[2])


def draw_heatmap_on_board(
    board_bgr: np.ndarray,
    rows: int,
    cols: int,
    de_grid: list[dict[str, Any]],
    out_path: Path,
) -> None:
    canvas = board_bgr.copy()
    h, w = canvas.shape[:2]

    idx = 0
    for r in range(rows):
        y0 = int(round(r * h / rows))
        y1 = int(round((r + 1) * h / rows))
        for c in range(cols):
            x0 = int(round(c * w / cols))
            x1 = int(round((c + 1) * w / cols))
            cell = de_grid[idx]
            idx += 1
            if not cell["used"]:
                continue
            de = float(cell["delta_e00"])
            color = de_color(de)

            overlay = canvas[y0:y1, x0:x1]
            patch = np.full_like(overlay, color, dtype=np.uint8)
            cv2.addWeighted(patch, 0.35, overlay, 0.65, 0, overlay)
            cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (36, 36, 36), 1)
            cv2.putText(
                canvas,
                f"{de:.2f}",
                (x0 + 6, y0 + max(18, (y1 - y0) // 2)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (250, 250, 250),
                1,
                cv2.LINE_AA,
            )

    cv2.imwrite(str(out_path), canvas)


def draw_detection_overlay(
    image_bgr: np.ndarray,
    board_quad: np.ndarray | None,
    sample_quad: np.ndarray | None,
    out_path: Path,
) -> None:
    canvas = image_bgr.copy()

    if board_quad is not None:
        cv2.polylines(canvas, [order_quad(board_quad).astype(np.int32)], isClosed=True, color=(40, 220, 120), thickness=3)
        cv2.putText(canvas, "BOARD", tuple(order_quad(board_quad)[0].astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (40, 220, 120), 2)

    if sample_quad is not None:
        cv2.polylines(canvas, [order_quad(sample_quad).astype(np.int32)], isClosed=True, color=(220, 120, 40), thickness=3)
        cv2.putText(canvas, "SAMPLE", tuple(order_quad(sample_quad)[0].astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 120, 40), 2)

    cv2.imwrite(str(out_path), canvas)


def compute_confidence(
    det_diag: dict[str, Any],
    lighting_range: float,
    board_valid_ratio: float,
    sample_valid_ratio: float,
) -> dict[str, float]:
    board_rect = det_diag.get("board_rectangularity", 0.0)
    sample_rect = det_diag.get("sample_rectangularity", 0.0)
    board_area_ratio = det_diag.get("board_area_ratio", 0.0)
    sample_ratio = det_diag.get("sample_area_ratio_to_board", 0.0)

    board_area_score = 1.0 - min(1.0, abs(board_area_ratio - 0.55) / 0.55)
    sample_area_score = 1.0 if 0.02 <= sample_ratio <= 0.45 else max(0.0, 1.0 - abs(sample_ratio - 0.12) / 0.25)

    geometry = float(np.clip(0.38 * board_rect + 0.20 * sample_rect + 0.26 * board_area_score + 0.16 * sample_area_score, 0.0, 1.0))
    lighting = float(np.clip(1.0 - max(0.0, lighting_range - 10.0) / 45.0, 0.0, 1.0))
    coverage = float(np.clip(0.5 * board_valid_ratio / 0.85 + 0.5 * sample_valid_ratio / 0.85, 0.0, 1.0))
    overall = float(np.clip(0.40 * geometry + 0.32 * lighting + 0.28 * coverage, 0.0, 1.0))

    return {
        "overall": overall,
        "geometry": geometry,
        "lighting": lighting,
        "coverage": coverage,
    }


def coarse_lighting_range(board_lab: np.ndarray, board_mask: np.ndarray, rows: int = 4, cols: int = 4) -> float:
    h, w = board_mask.shape
    values = []
    for r in range(rows):
        y0 = int(round(r * h / rows))
        y1 = int(round((r + 1) * h / rows))
        for c in range(cols):
            x0 = int(round(c * w / cols))
            x1 = int(round((c + 1) * w / cols))
            m = board_mask[y0:y1, x0:x1]
            if np.count_nonzero(m) < 100:
                continue
            values.append(float(np.mean(board_lab[y0:y1, x0:x1, 0][m])))
    if len(values) < 2:
        return 0.0
    return float(np.percentile(values, 95) - np.percentile(values, 5))


def resolve_targets(profile_targets: dict[str, float], target_override: dict[str, float] | None) -> dict[str, float]:
    if target_override is None:
        return {k: float(v) for k, v in profile_targets.items()}
    out = {k: float(v) for k, v in profile_targets.items()}
    for key in ("avg_delta_e00", "p95_delta_e00", "max_delta_e00"):
        if key in target_override and target_override[key] is not None:
            out[key] = float(target_override[key])
    return out


def make_quality_flags(
    confidence: dict[str, float],
    lighting_range: float,
    board_valid_ratio: float,
    sample_valid_ratio: float,
    p95_delta_e: float,
    max_delta_e: float,
    board_sharpness: float | None = None,
    sample_sharpness: float | None = None,
) -> list[str]:
    flags: list[str] = []
    if confidence["overall"] < 0.68:
        flags.append("low_overall_confidence")
    if confidence["geometry"] < 0.65:
        flags.append("geometry_uncertain")
    if lighting_range > 20:
        flags.append("lighting_non_uniform")
    if board_valid_ratio < 0.72:
        flags.append("board_effective_pixels_low")
    if sample_valid_ratio < 0.72:
        flags.append("sample_effective_pixels_low")
    if p95_delta_e > 8:
        flags.append("high_zone_variability")
    if max_delta_e > 12:
        flags.append("local_extreme_deviation")
    if board_sharpness is not None and board_sharpness < 26:
        flags.append("board_low_sharpness")
    if sample_sharpness is not None and sample_sharpness < 22:
        flags.append("sample_low_sharpness")
    return flags


def compute_sharpness(image_bgr: np.ndarray, mask: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    vals = lap[mask]
    if vals.size < 120:
        vals = lap.reshape(-1)
    return float(np.var(vals))


def build_capture_guidance(flags: list[str]) -> list[str]:
    tips: list[str] = []
    if "low_overall_confidence" in flags or "geometry_uncertain" in flags:
        tips.append("请让镜头与板面尽量垂直，并保证大板四角完整入镜。")
    if "lighting_non_uniform" in flags:
        tips.append("光照不均，建议使用固定光源并避免顶部阴影与局部强反光。")
    if "board_effective_pixels_low" in flags or "sample_effective_pixels_low" in flags:
        tips.append("有效采样像素偏少，建议减少遮挡、污渍和手写区域覆盖。")
    if "board_low_sharpness" in flags or "sample_low_sharpness" in flags:
        tips.append("图像清晰度不足，建议固定手机/相机并提高快门速度避免抖动。")
    if "high_zone_variability" in flags or "local_extreme_deviation" in flags:
        tips.append("建议同一批次拍 3 张后用融合判定（ensemble）降低误判。")
    if "ensemble_high_variability" in flags:
        tips.append("融合结果离散度较高，建议固定机位并增加拍摄张数到 5 张以上。")
    if "ensemble_insufficient_images" in flags:
        tips.append("融合判定样本不足，建议至少采集 3 张有效图像。")
    if any(f in flags for f in ("ensemble_avg_exceeds_target", "ensemble_p95_exceeds_target", "ensemble_max_exceeds_target")):
        tips.append("融合结果仍超阈值，优先执行工艺调参后再复拍复测。")
    if not tips:
        tips.append("拍摄质量良好，可直接用于自动判色。")
    return tips


def detect_aruco_board_quad(
    image_bgr: np.ndarray,
    dict_name: str = "DICT_4X4_50",
    ids_order: list[int] | None = None,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    if not hasattr(cv2, "aruco"):
        return None, {"found": False, "reason": "opencv_without_aruco"}
    if not hasattr(cv2.aruco, dict_name):
        return None, {"found": False, "reason": f"unknown_dict_{dict_name}"}

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    detector = cv2.aruco.ArucoDetector(dictionary)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None or len(ids) == 0:
        return None, {"found": False, "reason": "no_markers"}

    marker_ids = [int(x[0]) for x in ids]
    centers = [c.reshape(-1, 2).mean(axis=0).astype(np.float32) for c in corners]
    id_to_center = {mid: centers[i] for i, mid in enumerate(marker_ids)}

    if ids_order is not None:
        if len(ids_order) != 4:
            return None, {"found": False, "reason": "ids_order_must_4", "detected_ids": marker_ids}
        if any(mid not in id_to_center for mid in ids_order):
            return None, {"found": False, "reason": "required_ids_missing", "detected_ids": marker_ids}
        quad = np.array([id_to_center[mid] for mid in ids_order], dtype=np.float32)
        return order_quad(quad), {"found": True, "method": "aruco_ids_ordered", "detected_ids": marker_ids}

    if len(centers) < 4:
        return None, {"found": False, "reason": "less_than_4_markers", "detected_ids": marker_ids}

    pts = np.array(centers, dtype=np.float32)
    hull = cv2.convexHull(pts).reshape(-1, 2)
    if len(hull) < 4:
        return None, {"found": False, "reason": "convex_hull_less_than_4", "detected_ids": marker_ids}

    if len(hull) > 4:
        rect = cv2.minAreaRect(hull.astype(np.float32))
        quad = cv2.boxPoints(rect).astype(np.float32)
    else:
        quad = hull.astype(np.float32)
    return order_quad(quad), {"found": True, "method": "aruco_auto_hull", "detected_ids": marker_ids}


def quad_right_angle_score(quad: np.ndarray) -> float:
    q = order_quad(quad)
    vecs = []
    for i in range(4):
        v = q[(i + 1) % 4] - q[i]
        norm = np.linalg.norm(v)
        if norm < 1e-6:
            return 0.0
        vecs.append(v / norm)
    scores = []
    for i in range(4):
        cosv = abs(float(np.dot(vecs[i], vecs[(i + 1) % 4])))
        scores.append(1.0 - min(1.0, cosv))
    return float(np.mean(scores))


def find_inner_sample_on_board(board_bgr: np.ndarray) -> np.ndarray | None:
    h, w = board_bgr.shape[:2]
    area_total = float(h * w)

    gray = cv2.cvtColor(board_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edge = cv2.Canny(blur, 40, 130)
    edge = cv2.morphologyEx(edge, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best_quad = None
    best_score = -1.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < area_total * 0.012 or area > area_total * 0.50:
            continue

        rect = cv2.minAreaRect(cnt)
        rw, rh = rect[1]
        if rw < 35 or rh < 35:
            continue
        rect_area = float(rw * rh)
        if rect_area <= 0:
            continue
        fill = area / rect_area
        if fill < 0.45:
            continue

        box = cv2.boxPoints(rect).astype(np.float32)
        cx, cy = rect[0]
        if cx < w * 0.08 or cx > w * 0.92 or cy < h * 0.08 or cy > h * 0.95:
            continue

        rel = rect_area / area_total
        size_score = max(0.0, 1.0 - abs(rel - 0.12) / 0.15)
        aspect = max(rw, rh) / max(1.0, min(rw, rh))
        aspect_score = max(0.0, 1.0 - abs(aspect - 2.8) / 3.0)
        angle_score = quad_right_angle_score(box)
        score = 0.34 * fill + 0.25 * size_score + 0.21 * aspect_score + 0.20 * angle_score
        if score > best_score:
            best_score = score
            best_quad = box

    if best_quad is not None:
        return best_quad

    # Fallback: detect long strip sample via parallel vertical lines.
    lines = cv2.HoughLinesP(edge, 1, np.pi / 180, threshold=70, minLineLength=int(h * 0.12), maxLineGap=12)
    if lines is None:
        return None

    verticals: list[tuple[float, float, float, float, float]] = []
    for ln in lines[:, 0, :]:
        x1, y1, x2, y2 = map(float, ln)
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dy <= 3.0 * dx or dy < h * 0.12:
            continue
        x = (x1 + x2) / 2.0
        y0 = min(y1, y2)
        y1m = max(y1, y2)
        if x < w * 0.08 or x > w * 0.95:
            continue
        verticals.append((x, y0, y1m, dy, dx))

    best_pair = None
    best_pair_score = -1.0
    for i in range(len(verticals)):
        for j in range(i + 1, len(verticals)):
            l = verticals[i]
            r = verticals[j]
            if l[0] > r[0]:
                l, r = r, l
            width = r[0] - l[0]
            if width < w * 0.05 or width > w * 0.40:
                continue
            top = max(l[1], r[1])
            bottom = min(l[2], r[2])
            height_span = bottom - top
            if height_span < h * 0.16:
                continue
            area_rel = (width * height_span) / max(1.0, area_total)
            if area_rel < 0.01 or area_rel > 0.55:
                continue
            center_x = (l[0] + r[0]) * 0.5
            center_y = (top + bottom) * 0.5
            center_score = 1.0 - min(1.0, abs(center_x - w * 0.55) / (w * 0.55))
            parallel_score = 1.0 - min(1.0, abs(l[4] - r[4]) / 35.0)
            score = (
                0.36 * (height_span / h)
                + 0.24 * max(0.0, 1.0 - abs(area_rel - 0.12) / 0.18)
                + 0.24 * parallel_score
                + 0.16 * center_score
            )
            if center_y < h * 0.22:
                score *= 0.65
            if score > best_pair_score:
                best_pair_score = score
                best_pair = (l, r, top, bottom)

    if best_pair is None:
        return None

    l, r, top, bottom = best_pair
    quad = np.array(
        [
            [l[0], top],
            [r[0], top],
            [r[0], bottom],
            [l[0], bottom],
        ],
        dtype=np.float32,
    )
    return quad


def analyze_single_image(
    image_bgr: np.ndarray,
    grid_rows: int,
    grid_cols: int,
    profile_name: str,
    output_dir: Path,
    board_quad_override: np.ndarray | None = None,
    sample_quad_override: np.ndarray | None = None,
    target_override: dict[str, float] | None = None,
    aruco_config: dict[str, Any] | None = None,
    enable_shading_correction: bool = True,
) -> dict[str, Any]:
    cands = contour_candidates(image_bgr)
    board_cand, sample_cand, det_diag = choose_board_and_sample(cands, image_bgr.shape)
    det_diag["manual_board_override"] = bool(board_quad_override is not None)
    det_diag["manual_sample_override"] = bool(sample_quad_override is not None)
    aruco_info: dict[str, Any] = {"found": False, "enabled": bool(aruco_config and aruco_config.get("enabled", False))}

    if board_quad_override is None and aruco_config and aruco_config.get("enabled", False):
        aruco_quad, aruco_info = detect_aruco_board_quad(
            image_bgr=image_bgr,
            dict_name=str(aruco_config.get("dict_name", "DICT_4X4_50")),
            ids_order=aruco_config.get("ids_order"),
        )
        if aruco_quad is not None:
            board_quad_override = aruco_quad
            det_diag["aruco_applied"] = True
        else:
            det_diag["aruco_applied"] = False
    det_diag["aruco"] = aruco_info

    if board_quad_override is not None:
        board_quad = order_quad(board_quad_override)
        board_warp, m_board, _ = warp_quad(image_bgr, board_quad, target_long_side=1500)
        if det_diag.get("aruco_applied", False):
            board_source = "aruco"
        elif det_diag.get("manual_board_override", False):
            board_source = "manual"
        else:
            board_source = "override"
    else:
        if board_cand is None:
            raise RuntimeError("未能自动识别大板轮廓，请改用更规整拍摄角度或手动ROI模式。")
        board_warp, m_board, board_quad = warp_quad(image_bgr, board_cand.quad, target_long_side=1500)
        board_source = "auto"

    if sample_quad_override is not None:
        sample_quad = order_quad(sample_quad_override)
        sample_warp, _, _ = warp_quad(image_bgr, sample_quad, target_long_side=900)
        sample_poly = sample_quad.reshape(1, -1, 2).astype(np.float32)
        sample_on_board = cv2.perspectiveTransform(sample_poly, m_board).reshape(-1, 2)
        sample_source = "manual"
    else:
        sample_source = "inner_board_detection"
        sample_inner_quad = find_inner_sample_on_board(board_warp)
        if sample_inner_quad is not None:
            sample_warp, _, _ = warp_quad(board_warp, sample_inner_quad, target_long_side=900)
            inv_m_board = np.linalg.inv(m_board)
            sample_quad = cv2.perspectiveTransform(sample_inner_quad.reshape(1, -1, 2).astype(np.float32), inv_m_board).reshape(-1, 2)
            sample_on_board = order_quad(sample_inner_quad)
        else:
            if sample_cand is None:
                raise RuntimeError("未能自动识别小样轮廓，请避免遮挡并让小样完整入镜。")
            sample_source = "global_detection"
            sample_warp, _, sample_quad = warp_quad(image_bgr, sample_cand.quad, target_long_side=900)
            sample_poly = order_quad(sample_quad).reshape(1, -1, 2)
            sample_on_board = cv2.perspectiveTransform(sample_poly.astype(np.float32), m_board).reshape(-1, 2)

    board_area_px = float(image_bgr.shape[0] * image_bgr.shape[1])
    det_diag["board_source"] = board_source
    det_diag["board_area_ratio"] = float(cv2.contourArea(order_quad(board_quad).astype(np.float32)) / max(1.0, board_area_px))
    det_diag["board_rectangularity"] = max(float(det_diag.get("board_rectangularity", 0.0)), quad_right_angle_score(board_quad))
    sample_area_in_board = float(abs(cv2.contourArea(sample_on_board.astype(np.float32))))
    det_diag["sample_area_ratio_to_board"] = sample_area_in_board / max(1.0, float(board_warp.shape[0] * board_warp.shape[1]))
    det_diag["sample_rectangularity"] = max(float(det_diag.get("sample_rectangularity", 0.0)), quad_right_angle_score(sample_on_board))

    board_mask = build_material_mask(board_warp.shape[:2], border_ratio=0.04)
    board_mask &= grabcut_foreground_mask(board_warp)
    sample_mask = build_material_mask(sample_warp.shape[:2], border_ratio=0.06)

    invalid_board = build_invalid_mask(board_warp)
    invalid_sample = build_invalid_mask(sample_warp)
    board_mask &= ~invalid_board
    sample_mask &= ~invalid_sample

    board_mask_u8 = board_mask.astype(np.uint8)
    cv2.fillConvexPoly(board_mask_u8, sample_on_board.astype(np.int32), 0)
    board_mask = board_mask_u8.astype(bool)

    board_wb, board_gains = apply_gray_world(board_warp, board_mask)
    sample_wb, sample_gains = apply_gray_world(sample_warp, sample_mask)
    if enable_shading_correction:
        board_wb = apply_shading_correction(board_wb, board_mask)
        sample_wb = apply_shading_correction(sample_wb, sample_mask)

    board_tone = texture_suppress(board_wb)
    sample_tone = texture_suppress(sample_wb)
    board_sharpness = compute_sharpness(board_tone, board_mask)
    sample_sharpness = compute_sharpness(sample_tone, sample_mask)

    board_lab = bgr_to_lab_float(board_tone)
    sample_lab = bgr_to_lab_float(sample_tone)

    board_mean, board_std, board_used = robust_mean_lab(board_lab, board_mask)
    sample_mean, sample_std, sample_used = robust_mean_lab(sample_lab, sample_mask)

    inferred_profile, profile_metrics = infer_profile(board_tone, board_mask, profile_name)
    profile = PROFILES[inferred_profile]

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
                grid.append(
                    {
                        "row": r + 1,
                        "col": c + 1,
                        "used": False,
                        "delta_e00": None,
                        "valid_ratio": float(np.count_nonzero(cell_mask) / max(1, cell_mask.size)),
                    }
                )
                continue
            mean_lab, std_lab, cnt = robust_mean_lab(board_lab[y0:y1, x0:x1], cell_mask)
            de = float(ciede2000(mean_lab.reshape(1, 3), sample_vec)[0])
            de_values.append(de)
            grid.append(
                {
                    "row": r + 1,
                    "col": c + 1,
                    "used": True,
                    "valid_ratio": float(np.count_nonzero(cell_mask) / max(1, cell_mask.size)),
                    "used_pixels": cnt,
                    "delta_e00": de,
                    "board_lab": [float(x) for x in mean_lab],
                    "board_std": [float(x) for x in std_lab],
                }
            )

    if not de_values:
        raise RuntimeError("可用采样网格为空，请检查图像质量与遮挡。")

    de_np = np.array(de_values, dtype=np.float32)
    avg_de = float(np.mean(de_np))
    p95_de = float(np.percentile(de_np, 95))
    max_de = float(np.max(de_np))

    de_global = float(ciede2000(board_mean.reshape(1, 3), sample_mean.reshape(1, 3))[0])
    d_l, d_c, d_h = delta_components(board_mean, sample_mean)

    lighting_range = coarse_lighting_range(board_lab, board_mask)
    board_valid_ratio = float(np.count_nonzero(board_mask) / board_mask.size)
    sample_valid_ratio = float(np.count_nonzero(sample_mask) / sample_mask.size)
    confidence = compute_confidence(det_diag, lighting_range, board_valid_ratio, sample_valid_ratio)

    t = resolve_targets(profile["targets"], target_override)
    pass_color = avg_de <= t["avg_delta_e00"] and p95_de <= t["p95_delta_e00"] and max_de <= t["max_delta_e00"]
    passed = pass_color and confidence["overall"] >= 0.68

    recs = build_recommendations(d_l, d_c, d_h, profile["bias_thresholds"], confidence["overall"])
    quality_flags = make_quality_flags(
        confidence=confidence,
        lighting_range=lighting_range,
        board_valid_ratio=board_valid_ratio,
        sample_valid_ratio=sample_valid_ratio,
        p95_delta_e=p95_de,
        max_delta_e=max_de,
        board_sharpness=board_sharpness,
        sample_sharpness=sample_sharpness,
    )
    capture_guidance = build_capture_guidance(quality_flags)

    heatmap_path = output_dir / "elite_heatmap_board.png"
    draw_heatmap_on_board(board_warp, grid_rows, grid_cols, grid, heatmap_path)

    overlay_path = output_dir / "elite_detection_overlay.png"
    draw_detection_overlay(image_bgr, board_quad, sample_quad, overlay_path)

    cv2.imwrite(str(output_dir / "elite_board_warp.png"), board_warp)
    cv2.imwrite(str(output_dir / "elite_sample_warp.png"), sample_warp)

    mask_preview = np.zeros((max(board_warp.shape[0], sample_warp.shape[0]), board_warp.shape[1] + sample_warp.shape[1], 3), dtype=np.uint8)
    bw = cv2.cvtColor((board_mask.astype(np.uint8) * 255), cv2.COLOR_GRAY2BGR)
    sw = cv2.cvtColor((sample_mask.astype(np.uint8) * 255), cv2.COLOR_GRAY2BGR)
    mask_preview[: board_warp.shape[0], : board_warp.shape[1]] = bw
    mask_preview[: sample_warp.shape[0], board_warp.shape[1] : board_warp.shape[1] + sample_warp.shape[1]] = sw
    cv2.imwrite(str(output_dir / "elite_mask_preview.png"), mask_preview)

    return {
        "mode": "single_image",
        "profile": {
            "requested": profile_name,
            "used": inferred_profile,
            "metrics": profile_metrics,
            "targets": profile["targets"],
            "targets_used": t,
            "bias_thresholds": profile["bias_thresholds"],
            "capture_notes": profile["capture"],
        },
        "detection": {
            **det_diag,
            "sample_source": sample_source,
            "board_quad": order_quad(board_quad).tolist(),
            "sample_quad": order_quad(sample_quad).tolist(),
        },
        "preprocess": {
            "board_white_balance_gains_bgr": board_gains,
            "sample_white_balance_gains_bgr": sample_gains,
            "shading_correction": bool(enable_shading_correction),
            "lighting_range_L": lighting_range,
            "board_valid_ratio": board_valid_ratio,
            "sample_valid_ratio": sample_valid_ratio,
            "board_sharpness": board_sharpness,
            "sample_sharpness": sample_sharpness,
        },
        "result": {
            "pass": passed,
            "pass_color_only": pass_color,
            "confidence": confidence,
            "summary": {
                "global_delta_e00": de_global,
                "avg_delta_e00": avg_de,
                "p50_delta_e00": float(np.percentile(de_np, 50)),
                "p75_delta_e00": float(np.percentile(de_np, 75)),
                "p90_delta_e00": float(np.percentile(de_np, 90)),
                "p95_delta_e00": p95_de,
                "p99_delta_e00": float(np.percentile(de_np, 99)),
                "max_delta_e00": max_de,
                "dL": d_l,
                "dC": d_c,
                "dH_deg": d_h,
                "board_lab": [float(x) for x in board_mean],
                "sample_lab": [float(x) for x in sample_mean],
                "board_std": [float(x) for x in board_std],
                "sample_std": [float(x) for x in sample_std],
                "board_used_pixels": board_used,
                "sample_used_pixels": sample_used,
            },
            "recommendations": recs,
            "quality_flags": quality_flags,
            "capture_guidance": capture_guidance,
            "grid": grid,
        },
        "artifacts": {
            "overlay": str(overlay_path),
            "board_warp": str(output_dir / "elite_board_warp.png"),
            "sample_warp": str(output_dir / "elite_sample_warp.png"),
            "mask_preview": str(output_dir / "elite_mask_preview.png"),
            "heatmap": str(heatmap_path),
        },
    }

def align_pair_ecc(reference_bgr: np.ndarray, film_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    g_ref = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    g_film = cv2.cvtColor(film_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 120, 1e-7)
    try:
        cc, warp = cv2.findTransformECC(g_ref, g_film, warp, cv2.MOTION_AFFINE, criteria)
        if cc >= 0.75:
            aligned = cv2.warpAffine(
                film_bgr,
                warp,
                (reference_bgr.shape[1], reference_bgr.shape[0]),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return aligned, {"applied": True, "method": "ecc_affine", "correlation": float(cc), "matrix": warp.tolist()}
    except cv2.error:
        pass
    return film_bgr, {"applied": False, "reason": "ecc_failed"}


def analyze_dual_image(
    reference_bgr: np.ndarray,
    film_bgr: np.ndarray,
    grid_rows: int,
    grid_cols: int,
    profile_name: str,
    roi: ROI | None,
    output_dir: Path,
    target_override: dict[str, float] | None = None,
    enable_shading_correction: bool = True,
) -> dict[str, Any]:
    if reference_bgr.shape[:2] != film_bgr.shape[:2]:
        film_bgr = cv2.resize(film_bgr, (reference_bgr.shape[1], reference_bgr.shape[0]), interpolation=cv2.INTER_AREA)

    film_aligned, align_info = align_pair_ecc(reference_bgr, film_bgr)

    h, w = reference_bgr.shape[:2]
    if roi is None:
        roi = ROI(x=int(w * 0.04), y=int(h * 0.04), w=int(w * 0.92), h=int(h * 0.92))
    roi = ensure_roi_in_bounds(roi, w, h)

    ref_crop = reference_bgr[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    film_crop = film_aligned[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]

    ref_mask = build_material_mask(ref_crop.shape[:2], border_ratio=0.03)
    film_mask = build_material_mask(film_crop.shape[:2], border_ratio=0.03)
    ref_mask &= grabcut_foreground_mask(ref_crop)
    film_mask &= grabcut_foreground_mask(film_crop)
    ref_mask &= ~build_invalid_mask(ref_crop)
    film_mask &= ~build_invalid_mask(film_crop)

    ref_wb, gain_ref = apply_gray_world(ref_crop, ref_mask)
    film_wb, gain_film = apply_gray_world(film_crop, film_mask)
    if enable_shading_correction:
        ref_wb = apply_shading_correction(ref_wb, ref_mask)
        film_wb = apply_shading_correction(film_wb, film_mask)

    ref_tone = texture_suppress(ref_wb)
    film_tone = texture_suppress(film_wb)
    ref_sharpness = compute_sharpness(ref_tone, ref_mask)
    film_sharpness = compute_sharpness(film_tone, film_mask)
    ref_lab = bgr_to_lab_float(ref_tone)
    film_lab = bgr_to_lab_float(film_tone)

    ref_mean, ref_std, ref_used = robust_mean_lab(ref_lab, ref_mask)
    film_mean, film_std, film_used = robust_mean_lab(film_lab, film_mask)

    profile_used, profile_metrics = infer_profile(ref_tone, ref_mask, profile_name)
    profile = PROFILES[profile_used]

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

            ref_cell, ref_std_cell, cnt_ref = robust_mean_lab(ref_lab[y0:y1, x0:x1], m)
            film_cell, film_std_cell, cnt_film = robust_mean_lab(film_lab[y0:y1, x0:x1], m)

            de = float(ciede2000(ref_cell.reshape(1, 3), film_cell.reshape(1, 3))[0])
            d_l, d_c, d_h = delta_components(ref_cell, film_cell)

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
        raise RuntimeError("可用采样网格为空，请检查ROI和图像质量。")

    de_np = np.array(de_values, dtype=np.float32)
    avg_de = float(np.mean(de_np))
    p95_de = float(np.percentile(de_np, 95))
    max_de = float(np.max(de_np))

    d_l = float(np.median(np.array(d_ls, dtype=np.float32)))
    d_c = float(np.median(np.array(d_cs, dtype=np.float32)))
    d_h = circular_median_deg(np.array(d_hs, dtype=np.float32))

    de_global = float(ciede2000(ref_mean.reshape(1, 3), film_mean.reshape(1, 3))[0])

    lighting_range = coarse_lighting_range(ref_lab, ref_mask)
    det_diag = {
        "board_area_ratio": 0.9,
        "board_rectangularity": 0.95,
        "sample_area_ratio_to_board": 0.18,
        "sample_rectangularity": 0.90,
    }
    confidence = compute_confidence(
        det_diag=det_diag,
        lighting_range=lighting_range,
        board_valid_ratio=float(np.count_nonzero(ref_mask) / ref_mask.size),
        sample_valid_ratio=float(np.count_nonzero(film_mask) / film_mask.size),
    )

    targets = resolve_targets(profile["targets"], target_override)
    pass_color = avg_de <= targets["avg_delta_e00"] and p95_de <= targets["p95_delta_e00"] and max_de <= targets["max_delta_e00"]
    passed = pass_color and confidence["overall"] >= 0.68

    recs = build_recommendations(d_l, d_c, d_h, profile["bias_thresholds"], confidence["overall"])
    quality_flags = make_quality_flags(
        confidence=confidence,
        lighting_range=lighting_range,
        board_valid_ratio=float(np.count_nonzero(ref_mask) / ref_mask.size),
        sample_valid_ratio=float(np.count_nonzero(film_mask) / film_mask.size),
        p95_delta_e=p95_de,
        max_delta_e=max_de,
        board_sharpness=ref_sharpness,
        sample_sharpness=film_sharpness,
    )
    capture_guidance = build_capture_guidance(quality_flags)

    heatmap_path = output_dir / "elite_heatmap_dual.png"
    draw_heatmap_on_board(ref_crop, grid_rows, grid_cols, grid, heatmap_path)

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
            "confidence": confidence,
            "summary": {
                "global_delta_e00": de_global,
                "avg_delta_e00": avg_de,
                "p50_delta_e00": float(np.percentile(de_np, 50)),
                "p75_delta_e00": float(np.percentile(de_np, 75)),
                "p90_delta_e00": float(np.percentile(de_np, 90)),
                "p95_delta_e00": p95_de,
                "p99_delta_e00": float(np.percentile(de_np, 99)),
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


def build_target_override(avg: float | None, p95: float | None, max_v: float | None) -> dict[str, float] | None:
    if avg is None and p95 is None and max_v is None:
        return None
    out: dict[str, float] = {}
    if avg is not None:
        out["avg_delta_e00"] = float(avg)
    if p95 is not None:
        out["p95_delta_e00"] = float(p95)
    if max_v is not None:
        out["max_delta_e00"] = float(max_v)
    return out


def run_batch_single_mode(
    batch_dir: Path,
    image_paths: list[Path],
    rows: int,
    cols: int,
    profile: str,
    output_dir: Path,
    board_quad_override: np.ndarray | None,
    sample_quad_override: np.ndarray | None,
    target_override: dict[str, float] | None,
    aruco_config: dict[str, Any] | None,
    enable_shading_correction: bool,
    write_html: bool,
    action_rules_config: Path | None = None,
    decision_policy_config: Path | None = None,
    enable_decision_center: bool = True,
) -> dict[str, Any]:
    batch_rows: list[dict[str, Any]] = []
    summary_path_json = output_dir / "batch_summary.json"
    summary_path_csv = output_dir / "batch_summary.csv"

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(image_paths)
    ok = 0

    for idx, image_path in enumerate(image_paths, start=1):
        case_dir = output_dir / f"{idx:04d}_{image_path.stem}"
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            image = read_image(image_path)
            report = analyze_single_image(
                image_bgr=image,
                grid_rows=rows,
                grid_cols=cols,
                profile_name=profile,
                output_dir=case_dir,
                board_quad_override=board_quad_override,
                sample_quad_override=sample_quad_override,
                target_override=target_override,
                aruco_config=aruco_config,
                enable_shading_correction=enable_shading_correction,
            )
            attach_process_advice(report, action_rules_config)
            attach_decision_center(report, decision_policy_config, enabled=enable_decision_center)
            report["inputs"] = {"image": str(image_path), "grid": {"rows": rows, "cols": cols}}
            report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report_file = case_dir / "elite_color_match_report.json"
            report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if write_html:
                write_html_report(report, case_dir / "elite_color_match_report.html")

            result = report["result"]
            summary = result["summary"]
            row = {
                "image": str(image_path),
                "status": "ok",
                "pass": bool(result["pass"]),
                "profile": report["profile"]["used"],
                "confidence": float(result["confidence"]["overall"]),
                "avg_delta_e00": float(summary["avg_delta_e00"]),
                "p95_delta_e00": float(summary["p95_delta_e00"]),
                "max_delta_e00": float(summary["max_delta_e00"]),
                "report": str(report_file),
            }
            ok += 1
        except Exception as exc:  # noqa: BLE001
            row = {
                "image": str(image_path),
                "status": "error",
                "pass": False,
                "profile": "",
                "confidence": 0.0,
                "avg_delta_e00": None,
                "p95_delta_e00": None,
                "max_delta_e00": None,
                "report": "",
                "error": str(exc),
            }
        batch_rows.append(row)

    batch_result = {
        "batch_dir": str(batch_dir),
        "total": total,
        "ok": ok,
        "error": total - ok,
        "rows": batch_rows,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    summary_path_json.write_text(json.dumps(batch_result, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "image",
        "status",
        "pass",
        "profile",
        "confidence",
        "avg_delta_e00",
        "p95_delta_e00",
        "max_delta_e00",
        "report",
        "error",
    ]
    with summary_path_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in batch_rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    return {
        "total": total,
        "ok": ok,
        "error": total - ok,
        "summary_json": str(summary_path_json),
        "summary_csv": str(summary_path_csv),
    }


def run_ensemble_single_mode(
    image_paths: list[Path],
    rows: int,
    cols: int,
    profile: str,
    output_dir: Path,
    board_quad_override: np.ndarray | None,
    sample_quad_override: np.ndarray | None,
    target_override: dict[str, float] | None,
    aruco_config: dict[str, Any] | None,
    enable_shading_correction: bool,
    min_count: int,
    write_html: bool,
    action_rules_config: Path | None = None,
    decision_policy_config: Path | None = None,
    enable_decision_center: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    members: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []

    for idx, image_path in enumerate(image_paths, start=1):
        case_dir = output_dir / f"ensemble_{idx:04d}_{image_path.stem}"
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            image = read_image(image_path)
            report = analyze_single_image(
                image_bgr=image,
                grid_rows=rows,
                grid_cols=cols,
                profile_name=profile,
                output_dir=case_dir,
                board_quad_override=board_quad_override,
                sample_quad_override=sample_quad_override,
                target_override=target_override,
                aruco_config=aruco_config,
                enable_shading_correction=enable_shading_correction,
            )
            attach_process_advice(report, action_rules_config)
            attach_decision_center(report, decision_policy_config, enabled=enable_decision_center)
            report["inputs"] = {"image": str(image_path), "grid": {"rows": rows, "cols": cols}}
            report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report_path = case_dir / "elite_color_match_report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if write_html:
                write_html_report(report, case_dir / "elite_color_match_report.html")

            summary = report["result"]["summary"]
            conf = float(report["result"]["confidence"]["overall"])
            member = {
                "image": str(image_path),
                "status": "ok",
                "pass": bool(report["result"]["pass"]),
                "profile": report["profile"]["used"],
                "confidence": conf,
                "avg_delta_e00": float(summary["avg_delta_e00"]),
                "p95_delta_e00": float(summary["p95_delta_e00"]),
                "max_delta_e00": float(summary["max_delta_e00"]),
                "dL": float(summary.get("dL", 0.0)),
                "dC": float(summary.get("dC", 0.0)),
                "dH_deg": float(summary.get("dH_deg", 0.0)),
                "report": str(report_path),
            }
            reports.append(report)
        except Exception as exc:  # noqa: BLE001
            member = {
                "image": str(image_path),
                "status": "error",
                "pass": False,
                "profile": "",
                "confidence": 0.0,
                "avg_delta_e00": None,
                "p95_delta_e00": None,
                "max_delta_e00": None,
                "dL": None,
                "dC": None,
                "dH_deg": None,
                "report": "",
                "error": str(exc),
            }
        members.append(member)

    ok_members = [m for m in members if m["status"] == "ok"]
    if not ok_members:
        raise RuntimeError("ensemble mode failed: no valid reports")

    arr_avg = np.array([m["avg_delta_e00"] for m in ok_members], dtype=np.float32)
    arr_p95 = np.array([m["p95_delta_e00"] for m in ok_members], dtype=np.float32)
    arr_max = np.array([m["max_delta_e00"] for m in ok_members], dtype=np.float32)
    arr_conf = np.array([m["confidence"] for m in ok_members], dtype=np.float32)
    arr_dl = np.array([m["dL"] for m in ok_members], dtype=np.float32)
    arr_dc = np.array([m["dC"] for m in ok_members], dtype=np.float32)
    arr_dh = np.array([m["dH_deg"] for m in ok_members], dtype=np.float32)

    base = reports[0]
    targets_used = base["profile"]["targets_used"]
    bias_thresholds = base["profile"]["bias_thresholds"]
    median_conf = float(np.median(arr_conf))
    median_avg = float(np.median(arr_avg))
    median_p95 = float(np.median(arr_p95))
    median_max = float(np.median(arr_max))
    std_avg = float(np.std(arr_avg))
    pass_rate = float(np.mean([1.0 if m["pass"] else 0.0 for m in ok_members]))

    ensemble_flags: list[str] = []
    if len(ok_members) < min_count:
        ensemble_flags.append("ensemble_insufficient_images")
    if std_avg > 1.2:
        ensemble_flags.append("ensemble_high_variability")
    if median_conf < 0.72:
        ensemble_flags.append("ensemble_low_confidence")
    if median_avg > targets_used["avg_delta_e00"]:
        ensemble_flags.append("ensemble_avg_exceeds_target")
    if median_p95 > targets_used["p95_delta_e00"]:
        ensemble_flags.append("ensemble_p95_exceeds_target")
    if median_max > targets_used["max_delta_e00"]:
        ensemble_flags.append("ensemble_max_exceeds_target")

    ensemble_pass = (
        len(ok_members) >= min_count
        and median_conf >= 0.72
        and median_avg <= targets_used["avg_delta_e00"]
        and median_p95 <= targets_used["p95_delta_e00"]
        and median_max <= targets_used["max_delta_e00"]
        and std_avg <= 1.2
    )

    d_h_med = circular_median_deg(arr_dh)
    recs = build_recommendations(
        d_l=float(np.median(arr_dl)),
        d_c=float(np.median(arr_dc)),
        d_h=d_h_med,
        thresholds=bias_thresholds,
        confidence=median_conf,
    )
    if "ensemble_high_variability" in ensemble_flags:
        recs.append("同批次离散度偏高，建议固定工位并连续拍摄 3-5 张后再判定。")
    capture_guidance = build_capture_guidance(ensemble_flags)

    ensemble_report = {
        "mode": "ensemble_single",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inputs": {"images": [str(p) for p in image_paths], "grid": {"rows": rows, "cols": cols}, "profile_requested": profile},
        "profile": {
            "used": base["profile"]["used"],
            "targets_used": targets_used,
            "bias_thresholds": bias_thresholds,
        },
        "result": {
            "pass": ensemble_pass,
            "confidence": {
                "median": median_conf,
                "mean": float(np.mean(arr_conf)),
                "std": float(np.std(arr_conf)),
            },
            "summary": {
                "median_avg_delta_e00": median_avg,
                "median_p95_delta_e00": median_p95,
                "median_max_delta_e00": median_max,
                "mean_avg_delta_e00": float(np.mean(arr_avg)),
                "p90_avg_delta_e00": float(np.percentile(arr_avg, 90)),
                "avg_delta_e00_std": std_avg,
                "median_dL": float(np.median(arr_dl)),
                "median_dC": float(np.median(arr_dc)),
                "median_dH_deg": d_h_med,
                "single_pass_rate": pass_rate,
                "ok_images": len(ok_members),
                "error_images": len(members) - len(ok_members),
            },
            "quality_flags": ensemble_flags,
            "capture_guidance": capture_guidance,
            "recommendations": recs,
            "members": members,
        },
    }
    attach_process_advice(ensemble_report, action_rules_config)
    attach_decision_center(ensemble_report, decision_policy_config, enabled=enable_decision_center)

    ensemble_json = output_dir / "ensemble_report.json"
    ensemble_json.write_text(json.dumps(ensemble_report, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "image",
        "status",
        "pass",
        "profile",
        "confidence",
        "avg_delta_e00",
        "p95_delta_e00",
        "max_delta_e00",
        "dL",
        "dC",
        "dH_deg",
        "report",
        "error",
    ]
    ensemble_csv = output_dir / "ensemble_members.csv"
    with ensemble_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in members:
            writer.writerow({k: m.get(k, "") for k in fieldnames})

    ensemble_html = None
    if write_html:
        ensemble_html = output_dir / "ensemble_report.html"
        write_html_report(ensemble_report, ensemble_html)

    return {
        "total": len(image_paths),
        "ok": len(ok_members),
        "error": len(members) - len(ok_members),
        "pass": ensemble_pass,
        "report_json": str(ensemble_json),
        "report_csv": str(ensemble_csv),
        "report_html": str(ensemble_html) if ensemble_html is not None else None,
    }


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def write_html_report(report: dict[str, Any], html_path: Path) -> None:
    result = report.get("result", {})
    summary = result.get("summary", {})
    confidence = result.get("confidence", {})
    profile = report.get("profile", {})
    artifacts = report.get("artifacts", {})
    recs = result.get("recommendations", [])
    flags = result.get("quality_flags", [])
    guidance = result.get("capture_guidance", [])
    process_advice = report.get("process_advice", {})
    process_actions = process_advice.get("suggested_actions", []) if isinstance(process_advice, dict) else []
    process_meanings = process_advice.get("suggested_meanings", []) if isinstance(process_advice, dict) else []
    process_risk = process_advice.get("risk_level", "-") if isinstance(process_advice, dict) else "-"
    process_score = process_advice.get("risk_score", None) if isinstance(process_advice, dict) else None
    decision_center = report.get("decision_center", {})
    decision_code = decision_center.get("decision_code", "-") if isinstance(decision_center, dict) else "-"
    decision_priority = decision_center.get("priority", "-") if isinstance(decision_center, dict) else "-"
    decision_cost = decision_center.get("estimated_cost", None) if isinstance(decision_center, dict) else None
    decision_actions = decision_center.get("recommended_actions_top3", []) if isinstance(decision_center, dict) else []
    decision_scores = decision_center.get("stakeholder_scores", {}) if isinstance(decision_center, dict) else {}
    customer_score = decision_scores.get("customer_score")
    boss_score = decision_scores.get("boss_score")
    company_score = decision_scores.get("company_score")
    decision_msgs = decision_center.get("executive_messages", {}) if isinstance(decision_center, dict) else {}
    msg_customer = decision_msgs.get("customer", "-") if isinstance(decision_msgs, dict) else "-"
    msg_boss = decision_msgs.get("boss", "-") if isinstance(decision_msgs, dict) else "-"
    msg_company = decision_msgs.get("company", "-") if isinstance(decision_msgs, dict) else "-"
    avg_de = summary.get("avg_delta_e00", summary.get("median_avg_delta_e00"))
    p95_de = summary.get("p95_delta_e00", summary.get("median_p95_delta_e00"))
    max_de = summary.get("max_delta_e00", summary.get("median_max_delta_e00"))
    d_l = summary.get("dL", summary.get("median_dL"))
    d_c = summary.get("dC", summary.get("median_dC"))
    d_h = summary.get("dH_deg", summary.get("median_dH_deg"))
    conf_val = confidence.get("overall", confidence.get("median"))

    def fnum(v: Any) -> str:
        try:
            return f"{float(v):.3f}"
        except Exception:  # noqa: BLE001
            return "-"

    images_html = []
    for key in ("overlay", "heatmap", "board_warp", "sample_warp", "reference_used", "film_used"):
        path = artifacts.get(key)
        if not path:
            continue
        p = Path(path)
        if not p.exists():
            continue
        img_src = p.resolve().as_uri()
        images_html.append(
            f"<div class='imgbox'><div class='cap'>{escape(key)}</div><img src='{img_src}' alt='{escape(key)}'/></div>"
        )
    pass_cls = "ok" if result.get("pass") else "fail"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Elite Color Report</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; background:#0b1220; color:#e5e7eb; margin:0; padding:20px; }}
.wrap {{ max-width:1100px; margin:0 auto; }}
.card {{ background:#111827; border:1px solid #1f2937; border-radius:12px; padding:16px; margin-bottom:14px; }}
h1 {{ font-size:24px; margin:0 0 8px; }}
h2 {{ font-size:16px; margin:0 0 10px; color:#93c5fd; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
td,th {{ border:1px solid #1f2937; padding:8px; text-align:left; }}
th {{ color:#93c5fd; }}
.ok {{ color:#4ade80; font-weight:700; }}
.fail {{ color:#f87171; font-weight:700; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }}
.imgbox img {{ width:100%; border-radius:8px; border:1px solid #1f2937; }}
.cap {{ font-size:12px; margin:0 0 6px; color:#9ca3af; }}
ul {{ margin:8px 0 0 18px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>Elite Color Match Report</h1>
    <div>mode: <b>{escape(str(report.get("mode", "-")))}</b> | profile: <b>{escape(str(profile.get("used", "-")))}</b></div>
    <div>pass: <span class='{pass_cls}'>{escape(str(result.get("pass", False)))}</span></div>
    <div>generated_at: {escape(str(report.get("generated_at", "-")))}</div>
  </div>
  <div class="card">
    <h2>Summary</h2>
    <table>
      <tr><th>avg ΔE00</th><th>p95 ΔE00</th><th>max ΔE00</th><th>confidence</th><th>dL</th><th>dC</th><th>dH</th></tr>
      <tr>
        <td>{fnum(avg_de)}</td>
        <td>{fnum(p95_de)}</td>
        <td>{fnum(max_de)}</td>
        <td>{fnum(conf_val)}</td>
        <td>{fnum(d_l)}</td>
        <td>{fnum(d_c)}</td>
        <td>{fnum(d_h)}</td>
      </tr>
    </table>
  </div>
  <div class="card">
    <h2>Quality Flags</h2>
    <ul>{"".join(f"<li>{escape(str(x))}</li>" for x in flags) if flags else "<li>none</li>"}</ul>
  </div>
  <div class="card">
    <h2>Recommendations</h2>
    <ul>{"".join(f"<li>{escape(str(x))}</li>" for x in recs) if recs else "<li>none</li>"}</ul>
  </div>
  <div class="card">
    <h2>Capture Guidance</h2>
    <ul>{"".join(f"<li>{escape(str(x))}</li>" for x in guidance) if guidance else "<li>none</li>"}</ul>
  </div>
  <div class="card">
    <h2>Process Advice</h2>
    <div>risk_level: <b>{escape(str(process_risk))}</b> | risk_score: <b>{fnum(process_score)}</b></div>
    <div style="margin-top:8px;">Detected meanings:</div>
    <ul>{"".join(f"<li>{escape(str(x))}</li>" for x in process_meanings) if process_meanings else "<li>none</li>"}</ul>
    <div style="margin-top:8px;">Suggested actions:</div>
    <ul>{"".join(f"<li>{escape(str(x))}</li>" for x in process_actions) if process_actions else "<li>none</li>"}</ul>
  </div>
  <div class="card">
    <h2>Decision Center</h2>
    <div>decision: <b>{escape(str(decision_code))}</b> | priority: <b>{escape(str(decision_priority))}</b> | estimated_cost: <b>{fnum(decision_cost)}</b></div>
    <table style="margin-top:10px;">
      <tr><th>customer_score</th><th>boss_score</th><th>company_score</th></tr>
      <tr><td>{fnum(customer_score)}</td><td>{fnum(boss_score)}</td><td>{fnum(company_score)}</td></tr>
    </table>
    <div style="margin-top:8px;">Executive messages:</div>
    <ul>
      <li>{escape(str(msg_customer))}</li>
      <li>{escape(str(msg_boss))}</li>
      <li>{escape(str(msg_company))}</li>
    </ul>
    <div style="margin-top:8px;">Top actions:</div>
    <ul>{"".join(f"<li>{escape(str(x))}</li>" for x in decision_actions) if decision_actions else "<li>none</li>"}</ul>
  </div>
  <div class="card">
    <h2>Artifacts</h2>
    <div class="grid">{''.join(images_html) if images_html else '<div>No images</div>'}</div>
  </div>
</div>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Elite universal color matching engine")
    parser.add_argument("--mode", choices=["single", "dual"], default="single")

    parser.add_argument("--image", type=Path, help="single-image mode input (board + sample in one photo)")
    parser.add_argument("--reference", type=Path, help="dual mode reference image")
    parser.add_argument("--film", type=Path, help="dual mode film image")

    parser.add_argument("--profile", choices=["auto", "solid", "wood", "stone", "metallic", "high_gloss"], default="auto")
    parser.add_argument("--grid", default="6x8")
    parser.add_argument("--roi", type=parse_roi, default=None, help="dual mode ROI x,y,w,h")
    parser.add_argument("--board-roi", type=parse_roi, default=None, help="single mode board ROI x,y,w,h (manual override)")
    parser.add_argument("--sample-roi", type=parse_roi, default=None, help="single mode sample ROI x,y,w,h (manual override)")
    parser.add_argument("--board-quad", type=parse_quad, default=None, help="single mode board quad x1,y1;x2,y2;x3,y3;x4,y4")
    parser.add_argument("--sample-quad", type=parse_quad, default=None, help="single mode sample quad x1,y1;x2,y2;x3,y3;x4,y4")
    parser.add_argument("--target-avg", type=float, default=None, help="override target avg ΔE00")
    parser.add_argument("--target-p95", type=float, default=None, help="override target p95 ΔE00")
    parser.add_argument("--target-max", type=float, default=None, help="override target max ΔE00")
    parser.add_argument("--batch-dir", type=Path, default=None, help="single mode batch folder")
    parser.add_argument("--batch-glob", default="*.jpg,*.jpeg,*.png,*.bmp,*.tif,*.tiff,*.webp", help="comma-separated glob list for batch mode")
    parser.add_argument("--ensemble-dir", type=Path, default=None, help="single mode ensemble folder (same batch multi-shot)")
    parser.add_argument("--ensemble-images", type=parse_path_list, default=None, help="single mode explicit ensemble images, comma-separated")
    parser.add_argument("--ensemble-glob", default="*.jpg,*.jpeg,*.png,*.bmp,*.tif,*.tiff,*.webp", help="glob list for ensemble-dir")
    parser.add_argument("--ensemble-min-count", type=int, default=3, help="minimum valid images for ensemble pass")
    parser.add_argument("--recursive", action="store_true", help="batch mode recursive search")
    parser.add_argument("--use-aruco", action="store_true", help="single mode: use ArUco markers to locate board")
    parser.add_argument("--aruco-dict", default="DICT_4X4_50", help="ArUco dictionary name, e.g. DICT_4X4_50")
    parser.add_argument("--aruco-ids", type=parse_int_list, default=None, help="Optional marker IDs order TL,TR,BR,BL")
    parser.add_argument("--profile-config", type=Path, default=None, help="JSON file to override profile thresholds")
    parser.add_argument("--html-report", action="store_true", help="also write HTML report")
    parser.add_argument("--disable-shading-correction", action="store_true", help="disable illumination shading correction")
    parser.add_argument("--history-db", type=Path, default=None, help="SQLite history db path for drift analysis")
    parser.add_argument("--line-id", default=None, help="production line id for history tracking")
    parser.add_argument("--product-code", default=None, help="product code for history tracking")
    parser.add_argument("--lot-id", default=None, help="lot id for this run")
    parser.add_argument("--history-window", type=int, default=30, help="history window size for drift assessment")
    parser.add_argument("--action-rules-config", type=Path, default=None, help="JSON process action rules config")
    parser.add_argument("--disable-process-advice", action="store_true", help="disable process action advice generation")
    parser.add_argument("--decision-policy-config", type=Path, default=None, help="JSON decision center policy config")
    parser.add_argument("--disable-decision-center", action="store_true", help="disable decision center generation")
    parser.add_argument("--output-dir", type=Path, default=Path("./out_elite"))

    args = parser.parse_args()
    rows, cols = parse_grid(args.grid)
    target_override = build_target_override(args.target_avg, args.target_p95, args.target_max)
    enable_shading_correction = not args.disable_shading_correction
    default_action_rules_config = Path(__file__).resolve().parent / "process_action_rules.json"
    default_decision_policy_config = Path(__file__).resolve().parent / "decision_policy.default.json"
    action_rules_config: Path | None = None
    decision_policy_config: Path | None = None
    if args.action_rules_config is not None:
        if not args.action_rules_config.exists():
            raise FileNotFoundError(f"action rules config not found: {args.action_rules_config}")
        action_rules_config = args.action_rules_config
    elif not args.disable_process_advice and default_action_rules_config.exists():
        action_rules_config = default_action_rules_config
    if args.decision_policy_config is not None:
        if not args.decision_policy_config.exists():
            raise FileNotFoundError(f"decision policy config not found: {args.decision_policy_config}")
        decision_policy_config = args.decision_policy_config
    elif not args.disable_decision_center and default_decision_policy_config.exists():
        decision_policy_config = default_decision_policy_config

    if args.profile_config is not None:
        if not args.profile_config.exists():
            raise FileNotFoundError(f"profile config not found: {args.profile_config}")
        applied = apply_profile_config(args.profile_config)
        if not applied:
            raise RuntimeError("profile config loaded but no valid profile updates were applied")

    if args.history_db is not None:
        init_db(args.history_db)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    board_quad_override = args.board_quad
    sample_quad_override = args.sample_quad
    if board_quad_override is None and args.board_roi is not None:
        board_quad_override = roi_to_quad(args.board_roi)
    if sample_quad_override is None and args.sample_roi is not None:
        sample_quad_override = roi_to_quad(args.sample_roi)
    aruco_config = {"enabled": bool(args.use_aruco), "dict_name": args.aruco_dict, "ids_order": args.aruco_ids}

    if args.ensemble_images is not None or args.ensemble_dir is not None:
        if args.mode != "single":
            raise ValueError("ensemble mode supports --mode single only")
        if args.ensemble_images is not None and args.ensemble_dir is not None:
            raise ValueError("use either --ensemble-images or --ensemble-dir, not both")

        if args.ensemble_images is not None:
            image_paths = args.ensemble_images
        else:
            if args.ensemble_dir is None or not args.ensemble_dir.exists():
                raise FileNotFoundError(f"ensemble dir not found: {args.ensemble_dir}")
            patterns = [p.strip() for p in args.ensemble_glob.split(",") if p.strip()]
            image_paths = []
            for pattern in patterns:
                if args.recursive:
                    image_paths.extend(sorted(args.ensemble_dir.rglob(pattern)))
                else:
                    image_paths.extend(sorted(args.ensemble_dir.glob(pattern)))
        unique_paths = []
        seen = set()
        for p in image_paths:
            if not p.is_file():
                continue
            s = str(p.resolve())
            if s in seen:
                continue
            seen.add(s)
            unique_paths.append(p)
        if len(unique_paths) < 1:
            raise RuntimeError("ensemble mode found no image files")

        ens = run_ensemble_single_mode(
            image_paths=unique_paths,
            rows=rows,
            cols=cols,
            profile=args.profile,
            output_dir=output_dir,
            board_quad_override=board_quad_override,
            sample_quad_override=sample_quad_override,
            target_override=target_override,
            aruco_config=aruco_config,
            enable_shading_correction=enable_shading_correction,
            min_count=max(1, int(args.ensemble_min_count)),
            write_html=bool(args.html_report),
            action_rules_config=action_rules_config,
            decision_policy_config=decision_policy_config,
            enable_decision_center=not args.disable_decision_center,
        )
        if args.history_db is not None:
            try:
                ensemble_report = json.loads(Path(ens["report_json"]).read_text(encoding="utf-8"))
                record_run(
                    db_path=args.history_db,
                    report=ensemble_report,
                    line_id=args.line_id,
                    product_code=args.product_code,
                    lot_id=args.lot_id,
                    report_path=str(ens["report_json"]),
                )
            except Exception:  # noqa: BLE001
                pass
        print("MODE=ensemble_single")
        print(f"total={ens['total']}")
        print(f"ok={ens['ok']}")
        print(f"error={ens['error']}")
        print(f"pass={ens['pass']}")
        print(f"report_json={ens['report_json']}")
        print(f"report_csv={ens['report_csv']}")
        if ens.get("report_html"):
            print(f"report_html={ens['report_html']}")
        return

    if args.batch_dir is not None:
        if args.mode != "single":
            raise ValueError("batch mode currently supports --mode single only")
        if not args.batch_dir.exists():
            raise FileNotFoundError(f"batch dir not found: {args.batch_dir}")
        patterns = [p.strip() for p in args.batch_glob.split(",") if p.strip()]
        image_paths: list[Path] = []
        for pattern in patterns:
            if args.recursive:
                image_paths.extend(sorted(args.batch_dir.rglob(pattern)))
            else:
                image_paths.extend(sorted(args.batch_dir.glob(pattern)))
        # de-dup and keep files only
        unique = []
        seen = set()
        for p in image_paths:
            if not p.is_file():
                continue
            s = str(p.resolve())
            if s in seen:
                continue
            seen.add(s)
            unique.append(p)
        if not unique:
            raise RuntimeError("batch mode found no image files")

        batch = run_batch_single_mode(
            batch_dir=args.batch_dir,
            image_paths=unique,
            rows=rows,
            cols=cols,
            profile=args.profile,
            output_dir=output_dir,
            board_quad_override=board_quad_override,
            sample_quad_override=sample_quad_override,
            target_override=target_override,
            aruco_config=aruco_config,
            enable_shading_correction=enable_shading_correction,
            write_html=bool(args.html_report),
            action_rules_config=action_rules_config,
            decision_policy_config=decision_policy_config,
            enable_decision_center=not args.disable_decision_center,
        )
        if args.history_db is not None:
            try:
                batch_obj = json.loads(Path(batch["summary_json"]).read_text(encoding="utf-8"))
                for row in batch_obj.get("rows", []):
                    if row.get("status") != "ok":
                        continue
                    report_fp = row.get("report")
                    if not report_fp:
                        continue
                    report_obj = json.loads(Path(report_fp).read_text(encoding="utf-8"))
                    record_run(
                        db_path=args.history_db,
                        report=report_obj,
                        line_id=args.line_id,
                        product_code=args.product_code,
                        lot_id=args.lot_id,
                        report_path=report_fp,
                    )
            except Exception:  # noqa: BLE001
                pass
        print("MODE=batch_single")
        print(f"total={batch['total']}")
        print(f"ok={batch['ok']}")
        print(f"error={batch['error']}")
        print(f"summary_json={batch['summary_json']}")
        print(f"summary_csv={batch['summary_csv']}")
        return

    if args.mode == "single":
        if args.image is None:
            raise ValueError("single mode requires --image")
        image = read_image(args.image)
        report = analyze_single_image(
            image_bgr=image,
            grid_rows=rows,
            grid_cols=cols,
            profile_name=args.profile,
            output_dir=output_dir,
            board_quad_override=board_quad_override,
            sample_quad_override=sample_quad_override,
            target_override=target_override,
            aruco_config=aruco_config,
            enable_shading_correction=enable_shading_correction,
        )
        report["inputs"] = {"image": str(args.image), "grid": {"rows": rows, "cols": cols}}
    else:
        if args.reference is None or args.film is None:
            raise ValueError("dual mode requires --reference and --film")
        reference = read_image(args.reference)
        film = read_image(args.film)
        report = analyze_dual_image(
            reference_bgr=reference,
            film_bgr=film,
            grid_rows=rows,
            grid_cols=cols,
            profile_name=args.profile,
            roi=args.roi,
            output_dir=output_dir,
            target_override=target_override,
            enable_shading_correction=enable_shading_correction,
        )
        report["inputs"] = {
            "reference": str(args.reference),
            "film": str(args.film),
            "grid": {"rows": rows, "cols": cols},
        }
    attach_process_advice(report, action_rules_config)
    attach_decision_center(report, decision_policy_config, enabled=not args.disable_decision_center)

    report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_path = output_dir / "elite_color_match_report.json"

    if args.history_db is not None:
        assessment = assess_current_vs_history(
            db_path=args.history_db,
            report=report,
            line_id=args.line_id,
            product_code=args.product_code,
            window=max(5, int(args.history_window)),
        )
        report["history_assessment"] = assessment
        if assessment.get("enabled") and assessment.get("flags"):
            flags = report.get("result", {}).setdefault("quality_flags", [])
            guidance = report.get("result", {}).setdefault("capture_guidance", [])
            for flag in assessment.get("flags", []):
                _append_unique(flags, str(flag))
            if "history_drift_uptrend" in assessment.get("flags", []):
                _append_unique(guidance, "历史趋势显示色差在上升，建议检查原料批次和设备稳定性。")
            if "history_confidence_drop" in assessment.get("flags", []):
                _append_unique(guidance, "历史对比显示置信度下降，建议检查工位光照和镜头清洁状态。")
            if any(f in assessment.get("flags", []) for f in ("history_avg_outlier_high", "history_p95_outlier_high", "history_max_outlier_high")):
                _append_unique(guidance, "当前结果较历史基线偏高，建议先执行小步调参并复测。")
        try:
            report["policy_recommendation"] = recommend_policy_adjustments(
                db_path=args.history_db,
                line_id=args.line_id,
                product_code=args.product_code,
                lot_id=args.lot_id,
                window=max(20, int(args.history_window) * 4),
            )
        except Exception:  # noqa: BLE001
            pass

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = None
    if args.html_report:
        html_path = output_dir / "elite_color_match_report.html"
        write_html_report(report, html_path)

    if args.history_db is not None:
        try:
            record_run(
                db_path=args.history_db,
                report=report,
                line_id=args.line_id,
                product_code=args.product_code,
                lot_id=args.lot_id,
                report_path=str(report_path),
            )
        except Exception:  # noqa: BLE001
            pass

    summary = report["result"]["summary"]
    print(f"MODE={report['mode']}")
    print(f"PROFILE={report['profile']['used']}")
    print(f"PASS={report['result']['pass']}")
    print(f"confidence={report['result']['confidence']['overall']:.3f}")
    print(f"avg ΔE00={summary['avg_delta_e00']:.3f}")
    print(f"p95 ΔE00={summary['p95_delta_e00']:.3f}")
    print(f"max ΔE00={summary['max_delta_e00']:.3f}")
    print(f"report={report_path}")
    if html_path is not None:
        print(f"html={html_path}")


if __name__ == "__main__":
    main()
