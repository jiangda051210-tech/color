from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class ROI:
    x: int
    y: int
    w: int
    h: int


def parse_roi(text: str) -> ROI:
    parts = [p.strip() for p in text.split(',')]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    x, y, w, h = map(int, parts)
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("ROI width and height must be > 0")
    return ROI(x=x, y=y, w=w, h=h)


def parse_grid(text: str) -> tuple[int, int]:
    parts = text.lower().split('x')
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Grid must be like 6x8")
    rows, cols = map(int, parts)
    if rows <= 0 or cols <= 0:
        raise argparse.ArgumentTypeError("Grid rows/cols must be > 0")
    return rows, cols


def ensure_roi_in_bounds(roi: ROI, width: int, height: int) -> ROI:
    x = max(0, min(roi.x, width - 1))
    y = max(0, min(roi.y, height - 1))
    w = min(roi.w, width - x)
    h = min(roi.h, height - y)
    if w <= 0 or h <= 0:
        raise ValueError("ROI is out of image bounds")
    return ROI(x=x, y=y, w=w, h=h)


def default_roi(width: int, height: int, margin_ratio: float = 0.06) -> ROI:
    mx = int(width * margin_ratio)
    my = int(height * margin_ratio)
    return ROI(x=mx, y=my, w=width - 2 * mx, h=height - 2 * my)


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size > 0 else None
    if img is None:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    return img


def apply_white_balance(image_bgr: np.ndarray, roi: ROI) -> tuple[np.ndarray, list[float]]:
    patch = image_bgr[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    means = patch.reshape(-1, 3).mean(axis=0).astype(np.float64)
    gray = float(np.mean(means))
    gains = gray / np.maximum(means, 1e-6)
    balanced = np.clip(image_bgr.astype(np.float32) * gains.reshape(1, 1, 3), 0, 255).astype(np.uint8)
    return balanced, gains.tolist()


def align_film_to_reference(reference_bgr: np.ndarray, film_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    g_ref = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
    g_film = cv2.cvtColor(film_bgr, cv2.COLOR_BGR2GRAY)

    # Prefer ECC for production-like captures where geometry is mostly affine.
    g_ref_f = g_ref.astype(np.float32) / 255.0
    g_film_f = g_film.astype(np.float32) / 255.0
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 120, 1e-7)
    try:
        cc, warp = cv2.findTransformECC(g_ref_f, g_film_f, warp, cv2.MOTION_AFFINE, criteria)
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

    # Fallback to feature matching when ECC is unstable.
    orb = cv2.ORB_create(nfeatures=5000)
    k_ref, d_ref = orb.detectAndCompute(g_ref, None)
    k_film, d_film = orb.detectAndCompute(g_film, None)

    if d_ref is None or d_film is None or len(k_ref) < 20 or len(k_film) < 20:
        return film_bgr, {"applied": False, "reason": "insufficient_features"}

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn = matcher.knnMatch(d_film, d_ref, k=2)

    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)

    if len(good) < 12:
        return film_bgr, {"applied": False, "reason": "insufficient_matches", "matches": len(good)}

    src = np.float32([k_film[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k_ref[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)

    if homography is None:
        return film_bgr, {"applied": False, "reason": "homography_failed", "matches": len(good)}

    inliers = int(mask.sum()) if mask is not None else 0
    inlier_ratio = inliers / max(1, len(good))
    if inliers < 10 or inlier_ratio < 0.25:
        return film_bgr, {
            "applied": False,
            "reason": "homography_low_quality",
            "matches": len(good),
            "inliers": inliers,
            "inlier_ratio": float(inlier_ratio),
        }

    aligned = cv2.warpPerspective(film_bgr, homography, (reference_bgr.shape[1], reference_bgr.shape[0]))
    return aligned, {
        "applied": True,
        "method": "orb_homography",
        "matches": len(good),
        "inliers": inliers,
        "inlier_ratio": float(inlier_ratio),
        "matrix": homography.tolist(),
    }


def bgr_to_lab_float(image_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = np.empty_like(lab)
    out[..., 0] = lab[..., 0] * (100.0 / 255.0)
    out[..., 1] = lab[..., 1] - 128.0
    out[..., 2] = lab[..., 2] - 128.0
    return out


def robust_lab_mean(patch_lab: np.ndarray) -> np.ndarray:
    flat = patch_lab.reshape(-1, 3)
    l_values = flat[:, 0]
    p10 = np.percentile(l_values, 10)
    p90 = np.percentile(l_values, 90)
    mask = (l_values >= p10) & (l_values <= p90)
    if np.count_nonzero(mask) < max(20, int(0.1 * len(flat))):
        return flat.mean(axis=0)
    return flat[mask].mean(axis=0)


def build_grid_cells(roi: ROI, rows: int, cols: int) -> list[ROI]:
    cells: list[ROI] = []
    x_edges = np.linspace(roi.x, roi.x + roi.w, cols + 1)
    y_edges = np.linspace(roi.y, roi.y + roi.h, rows + 1)
    for r in range(rows):
        for c in range(cols):
            x0 = int(round(x_edges[c]))
            x1 = int(round(x_edges[c + 1]))
            y0 = int(round(y_edges[r]))
            y1 = int(round(y_edges[r + 1]))
            cells.append(ROI(x=x0, y=y0, w=max(1, x1 - x0), h=max(1, y1 - y0)))
    return cells


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    l1, a1, b1 = lab1[:, 0], lab1[:, 1], lab1[:, 2]
    l2, a2, b2 = lab2[:, 0], lab2[:, 1], lab2[:, 2]

    avg_lp = (l1 + l2) / 2.0
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

    delta_e = np.sqrt(
        (dl / sl) ** 2
        + (dc / sc) ** 2
        + (dhp / sh) ** 2
        + rt * (dc / sc) * (dhp / sh)
    )
    return delta_e


def circular_median_deg(deg_values: np.ndarray) -> float:
    radians = np.deg2rad(deg_values)
    sin_mean = np.mean(np.sin(radians))
    cos_mean = np.mean(np.cos(radians))
    return float(np.rad2deg(np.arctan2(sin_mean, cos_mean)))


def build_recommendations(d_l: np.ndarray, d_c: np.ndarray, d_h_deg: np.ndarray, de: np.ndarray) -> list[str]:
    recs: list[str] = []
    med_l = float(np.median(d_l))
    med_c = float(np.median(d_c))
    med_h = circular_median_deg(d_h_deg)

    if med_l > 0.35:
        recs.append(f"彩膜整体偏亮，建议降低明度（中位 dL={med_l:.2f}）。")
    elif med_l < -0.35:
        recs.append(f"彩膜整体偏暗，建议提高明度（中位 dL={med_l:.2f}）。")

    if med_c > 0.35:
        recs.append(f"彩膜饱和度偏高，建议降低彩度（中位 dC={med_c:.2f}）。")
    elif med_c < -0.35:
        recs.append(f"彩膜饱和度偏低，建议增加彩度（中位 dC={med_c:.2f}）。")

    if abs(med_h) > 2.0:
        direction = "逆时针" if med_h > 0 else "顺时针"
        recs.append(f"存在色相系统偏移，建议 {direction} 微调色相（中位 dh={med_h:.1f}°）。")

    if float(np.std(de)) > 0.85:
        recs.append("颜色不均匀，优先检查涂布/印刷均匀性、烘箱温区和张力稳定性。")

    if not recs:
        recs.append("颜色偏差稳定且较小，当前工艺参数可维持。")

    return recs


def score_label(value: float) -> str:
    if value <= 0.8:
        return "PERFECT"
    if value <= 1.5:
        return "GOOD"
    if value <= 2.5:
        return "WARNING"
    return "FAIL"


def de_to_bgr(value: float) -> tuple[int, int, int]:
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


def draw_heatmap(rows: int, cols: int, de_values: np.ndarray, out_path: Path) -> None:
    cell_w, cell_h = 110, 80
    pad = 16
    width = cols * cell_w + pad * 2
    height = rows * cell_h + pad * 2 + 32
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:] = (20, 20, 20)

    idx = 0
    for r in range(rows):
        for c in range(cols):
            x0 = pad + c * cell_w
            y0 = pad + r * cell_h
            x1 = x0 + cell_w - 2
            y1 = y0 + cell_h - 2
            de = float(de_values[idx])
            color = de_to_bgr(de)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), color, thickness=-1)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (15, 15, 15), thickness=1)
            cv2.putText(
                canvas,
                f"{de:.2f}",
                (x0 + 12, y0 + 44),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            idx += 1

    cv2.putText(
        canvas,
        "DeltaE00 Heatmap (sample vs film)",
        (pad, height - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )

    cv2.imwrite(str(out_path), canvas)


def analyze(
    reference_bgr: np.ndarray,
    film_bgr: np.ndarray,
    roi: ROI,
    rows: int,
    cols: int,
) -> dict[str, Any]:
    ref_lab = bgr_to_lab_float(reference_bgr)
    film_lab = bgr_to_lab_float(film_bgr)

    cells = build_grid_cells(roi, rows, cols)
    ref_means = []
    film_means = []

    for cell in cells:
        ref_patch = ref_lab[cell.y : cell.y + cell.h, cell.x : cell.x + cell.w]
        film_patch = film_lab[cell.y : cell.y + cell.h, cell.x : cell.x + cell.w]
        ref_means.append(robust_lab_mean(ref_patch))
        film_means.append(robust_lab_mean(film_patch))

    ref_arr = np.stack(ref_means, axis=0)
    film_arr = np.stack(film_means, axis=0)
    de = ciede2000(ref_arr, film_arr)

    d_l = film_arr[:, 0] - ref_arr[:, 0]
    c_ref = np.sqrt(ref_arr[:, 1] ** 2 + ref_arr[:, 2] ** 2)
    c_film = np.sqrt(film_arr[:, 1] ** 2 + film_arr[:, 2] ** 2)
    d_c = c_film - c_ref

    h_ref = np.degrees(np.arctan2(ref_arr[:, 2], ref_arr[:, 1]))
    h_film = np.degrees(np.arctan2(film_arr[:, 2], film_arr[:, 1]))
    d_h = (h_film - h_ref + 180.0) % 360.0 - 180.0

    cell_reports = []
    for idx, cell in enumerate(cells):
        cell_reports.append(
            {
                "index": idx + 1,
                "row": idx // cols + 1,
                "col": idx % cols + 1,
                "roi": {"x": cell.x, "y": cell.y, "w": cell.w, "h": cell.h},
                "delta_e00": float(de[idx]),
                "dL": float(d_l[idx]),
                "dC": float(d_c[idx]),
                "dH_deg": float(d_h[idx]),
                "grade": score_label(float(de[idx])),
                "sample_lab": [float(x) for x in ref_arr[idx]],
                "film_lab": [float(x) for x in film_arr[idx]],
            }
        )

    avg_de = float(np.mean(de))
    p95_de = float(np.percentile(de, 95))
    max_de = float(np.max(de))

    return {
        "summary": {
            "avg_delta_e00": avg_de,
            "p95_delta_e00": p95_de,
            "max_delta_e00": max_de,
            "median_dL": float(np.median(d_l)),
            "median_dC": float(np.median(d_c)),
            "median_dH_deg": circular_median_deg(d_h),
            "uniformity_std_delta_e00": float(np.std(de)),
        },
        "cells": cell_reports,
        "de_values": de.tolist(),
        "recommendations": build_recommendations(d_l, d_c, d_h, de),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatic color match engine for sample vs film.")
    parser.add_argument("--reference", required=True, type=Path, help="Path to sample/reference image")
    parser.add_argument("--film", required=True, type=Path, help="Path to film image")
    parser.add_argument("--output-dir", type=Path, default=Path("./out"), help="Output folder")
    parser.add_argument("--grid", default="6x8", help="Grid size, e.g. 6x8")
    parser.add_argument("--roi", type=parse_roi, default=None, help="Analysis ROI x,y,w,h")
    parser.add_argument("--wb-roi", type=parse_roi, default=None, help="White-balance ROI x,y,w,h")
    parser.add_argument("--target-avg", type=float, default=1.2)
    parser.add_argument("--target-p95", type=float, default=2.0)
    parser.add_argument("--target-max", type=float, default=3.0)
    parser.add_argument("--no-align", action="store_true", help="Disable auto alignment")
    parser.add_argument("--save-debug", action="store_true", help="Save aligned and wb images")

    args = parser.parse_args()
    rows, cols = parse_grid(args.grid)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_bgr = read_image(args.reference)
    film_bgr = read_image(args.film)

    if reference_bgr.shape[:2] != film_bgr.shape[:2]:
        film_bgr = cv2.resize(film_bgr, (reference_bgr.shape[1], reference_bgr.shape[0]), interpolation=cv2.INTER_AREA)

    align_info: dict[str, Any] = {"applied": False, "reason": "disabled"}
    if not args.no_align:
        film_bgr, align_info = align_film_to_reference(reference_bgr, film_bgr)

    wb_info: dict[str, Any] = {"enabled": False}
    if args.wb_roi is not None:
        wb_ref_roi = ensure_roi_in_bounds(args.wb_roi, reference_bgr.shape[1], reference_bgr.shape[0])
        wb_film_roi = ensure_roi_in_bounds(args.wb_roi, film_bgr.shape[1], film_bgr.shape[0])
        reference_bgr, gain_ref = apply_white_balance(reference_bgr, wb_ref_roi)
        film_bgr, gain_film = apply_white_balance(film_bgr, wb_film_roi)
        wb_info = {
            "enabled": True,
            "roi": {"x": wb_ref_roi.x, "y": wb_ref_roi.y, "w": wb_ref_roi.w, "h": wb_ref_roi.h},
            "reference_gains_bgr": gain_ref,
            "film_gains_bgr": gain_film,
        }

    if args.roi is None:
        roi = default_roi(reference_bgr.shape[1], reference_bgr.shape[0])
    else:
        roi = ensure_roi_in_bounds(args.roi, reference_bgr.shape[1], reference_bgr.shape[0])

    result = analyze(reference_bgr, film_bgr, roi, rows=rows, cols=cols)

    summary = result["summary"]
    passed = (
        summary["avg_delta_e00"] <= args.target_avg
        and summary["p95_delta_e00"] <= args.target_p95
        and summary["max_delta_e00"] <= args.target_max
    )

    report = {
        "inputs": {
            "reference": str(args.reference),
            "film": str(args.film),
            "grid": {"rows": rows, "cols": cols},
            "roi": {"x": roi.x, "y": roi.y, "w": roi.w, "h": roi.h},
        },
        "targets": {
            "avg_delta_e00": args.target_avg,
            "p95_delta_e00": args.target_p95,
            "max_delta_e00": args.target_max,
        },
        "alignment": align_info,
        "white_balance": wb_info,
        "result": {
            "pass": passed,
            "summary": summary,
            "recommendations": result["recommendations"],
            "cells": result["cells"],
        },
    }

    report_path = output_dir / "color_match_report.json"
    heatmap_path = output_dir / "deltae_heatmap.png"

    draw_heatmap(rows, cols, np.array(result["de_values"], dtype=np.float32), heatmap_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.save_debug:
        cv2.imwrite(str(output_dir / "reference_used.png"), reference_bgr)
        cv2.imwrite(str(output_dir / "film_used.png"), film_bgr)

    print(f"PASS={passed}")
    print(f"avg ΔE00={summary['avg_delta_e00']:.3f}")
    print(f"p95 ΔE00={summary['p95_delta_e00']:.3f}")
    print(f"max ΔE00={summary['max_delta_e00']:.3f}")
    print(f"report={report_path}")
    print(f"heatmap={heatmap_path}")


if __name__ == "__main__":
    main()
