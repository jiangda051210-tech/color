"""
SENIA Elite — 专家级对色引擎
============================
模拟对色老员工的工作方式:
  1. 多板一致性检测 — 找出最不匹配的板子
  2. 相邻边界对比 — 沿接缝线取色对比
  3. 方向性诊断 — "偏黄0.3度+偏暗0.8度"
  4. 木纹纹理一致性 — 纹理方向/密度对比
  5. 综合专家判定 — 中文摘要 + 放行建议

设计理念:
  老员工看的是 "整体感觉" 而非单个数字.
  本模块输出的是 "人话" 而非 ΔE 表格.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from elite_color_science import ciede2000_scalar, bgr_to_lab_float32


# ─── 板材区域检测 ──────────────────────────────────────────

def _detect_plank_regions(image_bgr: np.ndarray, min_area_ratio: float = 0.01,
                          max_area_ratio: float = 0.75) -> list[dict[str, Any]]:
    """检测图像中的所有板材区域(矩形). 返回按面积降序排列."""
    h, w = image_bgr.shape[:2]
    total_area = float(h * w)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # 多策略边缘检测 + K-Means色彩分割
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 20, 80)
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 5)
    combined = cv2.bitwise_or(edges, cv2.bitwise_or(otsu, adapt))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=3)
    closed = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

    contours_raw, _ = cv2.findContours(closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = list(contours_raw)

    # 同时用LAB色彩分割找候选
    small = cv2.resize(image_bgr, (300, int(300 * h / w)), interpolation=cv2.INTER_AREA)
    lab_small = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    pixels_flat = lab_small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, _ = cv2.kmeans(pixels_flat, 4, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    labels_2d = labels.reshape(lab_small.shape[:2])
    scale_y, scale_x = h / lab_small.shape[0], w / lab_small.shape[1]
    for lbl in range(4):
        mask_small = (labels_2d == lbl).astype(np.uint8) * 255
        mask_full = cv2.resize(mask_small, (w, h), interpolation=cv2.INTER_NEAREST)
        seg_contours, _ = cv2.findContours(mask_full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(seg_contours)

    planks = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        ratio = area / total_area
        if ratio < min_area_ratio or ratio > max_area_ratio:
            continue
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect).astype(np.int32)
        rect_area = max(rect[1][0] * rect[1][1], 1)
        rectangularity = area / rect_area
        if rectangularity < 0.25:
            continue

        # 提取区域颜色信息
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillConvexPoly(mask, box, 255)
        lab = bgr_to_lab_float32(image_bgr)
        pixels = lab[mask > 0]
        if pixels.shape[0] < 100:
            continue

        mean_L = float(pixels[:, 0].mean())
        mean_a = float(pixels[:, 1].mean())
        mean_b = float(pixels[:, 2].mean())
        chroma = math.sqrt(mean_a ** 2 + mean_b ** 2)

        # 纹理复杂度
        roi_gray = gray.copy()
        roi_gray[mask == 0] = 0
        x0, y0 = box[:, 0].min(), box[:, 1].min()
        x1, y1 = box[:, 0].max(), box[:, 1].max()
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        crop = gray[y0:y1, x0:x1]
        texture = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size > 100 else 0

        # 背景判断: 水泥地面 = 低色度+低纹理
        is_background = chroma < 5 and texture < 80

        planks.append({
            "box": box,
            "center": (int(rect[0][0]), int(rect[0][1])),
            "area_ratio": round(ratio, 4),
            "rectangularity": round(rectangularity, 3),
            "mean_lab": (round(mean_L, 2), round(mean_a, 2), round(mean_b, 2)),
            "chroma": round(chroma, 2),
            "texture": round(texture, 1),
            "is_background": is_background,
        })

    # 过滤背景, 按面积降序
    product_planks = [p for p in planks if not p["is_background"]]
    if not product_planks:
        product_planks = sorted(planks, key=lambda p: p["chroma"], reverse=True)[:5]
    product_planks.sort(key=lambda p: p["area_ratio"], reverse=True)

    # 编号
    for idx, p in enumerate(product_planks):
        p["plank_id"] = idx + 1

    return product_planks


# ─── 多板一致性检测 ──────────────────────────────────────

def expert_multi_plank_consistency(image_bgr: np.ndarray) -> dict[str, Any]:
    """检测所有板材的一致性. 模拟老员工一眼扫过所有板子."""
    planks = _detect_plank_regions(image_bgr)
    n = len(planks)

    if n < 2:
        return {
            "plank_count": n,
            "consistency": "insufficient_planks",
            "human_summary": f"仅检测到{n}块板材, 无法进行一致性对比",
            "planks": planks,
        }

    # 两两对比
    matrix = [[0.0] * n for _ in range(n)]
    worst_pair = (0, 1)
    worst_de = 0.0
    best_pair = (0, 1)
    best_de = float("inf")
    pair_details = []

    for i in range(n):
        for j in range(i + 1, n):
            lab_i = planks[i]["mean_lab"]
            lab_j = planks[j]["mean_lab"]
            de = ciede2000_scalar(lab_i[0], lab_i[1], lab_i[2],
                                  lab_j[0], lab_j[1], lab_j[2])
            de_val = de["total"]
            matrix[i][j] = round(de_val, 3)
            matrix[j][i] = round(de_val, 3)

            diagnosis = _directional_diagnosis(lab_i, lab_j, "wood")

            pair_details.append({
                "plank_a": i + 1, "plank_b": j + 1,
                "delta_e": round(de_val, 3),
                "diagnosis": diagnosis["short"],
            })

            if de_val > worst_de:
                worst_de = de_val
                worst_pair = (i, j)
            if de_val < best_de:
                best_de = de_val
                best_pair = (i, j)

    # 综合判定
    avg_de = sum(p["delta_e"] for p in pair_details) / max(len(pair_details), 1)

    if worst_de < 1.0:
        level = "excellent"
        emoji = "优秀"
    elif worst_de < 2.0:
        level = "good"
        emoji = "良好"
    elif worst_de < 3.5:
        level = "acceptable"
        emoji = "可接受"
    else:
        level = "poor"
        emoji = "不合格"

    # 找出最不一致的板子
    outlier_id = None
    if n >= 3:
        plank_avg_de = []
        for i in range(n):
            des = [matrix[i][j] for j in range(n) if j != i]
            plank_avg_de.append(sum(des) / max(len(des), 1))
        outlier_idx = int(np.argmax(plank_avg_de))
        if plank_avg_de[outlier_idx] > avg_de * 1.3:
            outlier_id = outlier_idx + 1

    # 生成人话总结
    summary_parts = [f"共检测到{n}块板材, 整体一致性: {emoji}"]
    summary_parts.append(f"平均色差ΔE={avg_de:.2f}, 最大色差ΔE={worst_de:.2f}")
    if worst_de >= 2.0:
        wi, wj = worst_pair
        diag = _directional_diagnosis(planks[wi]["mean_lab"], planks[wj]["mean_lab"], "wood")
        summary_parts.append(f"{wi+1}号板与{wj+1}号板色差最大: {diag['short']}")
    if outlier_id:
        summary_parts.append(f"⚠ {outlier_id}号板与其他板差异最大, 建议重点检查")

    return {
        "plank_count": n,
        "consistency_level": level,
        "avg_delta_e": round(avg_de, 3),
        "worst_delta_e": round(worst_de, 3),
        "worst_pair": [worst_pair[0] + 1, worst_pair[1] + 1],
        "best_pair": [best_pair[0] + 1, best_pair[1] + 1],
        "outlier_plank": outlier_id,
        "comparison_matrix": matrix,
        "pair_details": pair_details,
        "planks": planks,
        "human_summary": "。".join(summary_parts) + "。",
    }


# ─── 方向性诊断 ──────────────────────────────────────────

def _directional_diagnosis(lab_ref: tuple, lab_sample: tuple,
                            profile: str = "wood") -> dict[str, str]:
    """将LAB差异转为老员工能说的话."""
    dL = lab_sample[0] - lab_ref[0]
    da = lab_sample[1] - lab_ref[1]
    db = lab_sample[2] - lab_ref[2]

    # 材质相关容差
    tol = {"wood": 0.4, "stone": 0.5, "solid": 0.2, "metallic": 0.3}.get(profile, 0.3)

    parts = []
    actions = []

    if abs(dL) > tol:
        degree = "明显" if abs(dL) > 1.5 else "略"
        if dL > 0:
            parts.append(f"{degree}偏亮{abs(dL):.1f}度")
            actions.append("降低油墨浓度或减薄涂层")
        else:
            parts.append(f"{degree}偏暗{abs(dL):.1f}度")
            actions.append("提高油墨浓度或加厚涂层")

    if abs(da) > tol:
        degree = "明显" if abs(da) > 1.0 else "略"
        if da > 0:
            parts.append(f"{degree}偏红{abs(da):.1f}")
            actions.append("减少红色/品红油墨")
        else:
            parts.append(f"{degree}偏绿{abs(da):.1f}")
            actions.append("增加红色/品红油墨")

    if abs(db) > tol:
        degree = "明显" if abs(db) > 1.0 else "略"
        if db > 0:
            parts.append(f"{degree}偏黄{abs(db):.1f}")
            actions.append("减少黄色油墨")
        else:
            parts.append(f"{degree}偏蓝{abs(db):.1f}")
            actions.append("增加黄色油墨")

    if not parts:
        return {"short": "色差极小, 可忽略", "detail": "无明显偏差", "actions": []}

    de = ciede2000_scalar(lab_ref[0], lab_ref[1], lab_ref[2],
                          lab_sample[0], lab_sample[1], lab_sample[2])

    short = " + ".join(parts) + f" (ΔE={de['total']:.2f})"
    return {"short": short, "detail": " + ".join(parts), "actions": actions, "dE": round(de["total"], 3)}


def expert_directional_diagnosis(lab_ref: tuple, lab_sample: tuple,
                                  profile: str = "wood") -> dict[str, Any]:
    """公开接口: 方向性色差诊断."""
    return _directional_diagnosis(lab_ref, lab_sample, profile)


# ─── 纹理一致性检测 ──────────────────────────────────────

def expert_texture_consistency(image_bgr: np.ndarray,
                                planks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """检查木纹方向和密度是否一致."""
    if planks is None:
        planks = _detect_plank_regions(image_bgr)
    if len(planks) < 2:
        return {"texture_consistent": True, "issues": [], "human_summary": "板材不足, 无法对比纹理"}

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    grain_infos = []
    for p in planks:
        box = p["box"]
        x0, y0 = max(0, box[:, 0].min()), max(0, box[:, 1].min())
        x1, y1 = min(w, box[:, 0].max()), min(h, box[:, 1].max())
        crop = gray[y0:y1, x0:x1]
        if crop.size < 400:
            grain_infos.append({"direction": 0, "density": 0, "valid": False})
            continue

        # 梯度方向 → 木纹方向
        gx = cv2.Sobel(crop, cv2.CV_64F, 1, 0, ksize=5)
        gy = cv2.Sobel(crop, cv2.CV_64F, 0, 1, ksize=5)
        angles = np.arctan2(gy, gx + 1e-8)
        mag = np.sqrt(gx ** 2 + gy ** 2)
        # 加权主方向
        strong = mag > np.percentile(mag, 70)
        if strong.sum() < 50:
            grain_infos.append({"direction": 0, "density": 0, "valid": False})
            continue
        dominant_angle = float(np.degrees(np.median(angles[strong])))

        # 纹理密度 (高频能量)
        f = np.fft.fft2(crop.astype(np.float32))
        fshift = np.fft.fftshift(f)
        magnitude = np.abs(fshift)
        ch, cw = magnitude.shape[0] // 2, magnitude.shape[1] // 2
        high_freq = magnitude.copy()
        high_freq[ch - 5:ch + 5, cw - 5:cw + 5] = 0  # 去除DC
        density = float(high_freq.mean())

        grain_infos.append({
            "direction": round(dominant_angle, 1),
            "density": round(density, 1),
            "valid": True,
        })

    # 比较
    valid = [(i, g) for i, g in enumerate(grain_infos) if g["valid"]]
    issues = []
    if len(valid) >= 2:
        dirs = [g["direction"] for _, g in valid]
        dens = [g["density"] for _, g in valid]
        mean_dir = float(np.median(dirs))
        mean_den = float(np.median(dens))

        for idx, g in valid:
            dir_diff = abs(g["direction"] - mean_dir)
            if dir_diff > 180:
                dir_diff = 360 - dir_diff
            if dir_diff > 25:
                issues.append({
                    "plank": idx + 1,
                    "issue": f"木纹方向偏离{dir_diff:.0f}°",
                    "severity": "high" if dir_diff > 45 else "medium",
                })
            den_diff = abs(g["density"] - mean_den) / max(mean_den, 1)
            if den_diff > 0.3:
                issues.append({
                    "plank": idx + 1,
                    "issue": f"木纹密度偏差{den_diff*100:.0f}%",
                    "severity": "high" if den_diff > 0.5 else "medium",
                })

    summary = "木纹一致性良好" if not issues else f"发现{len(issues)}项纹理差异: " + "; ".join(i["issue"] for i in issues[:3])

    return {
        "texture_consistent": len(issues) == 0,
        "grain_infos": grain_infos,
        "issues": issues,
        "human_summary": summary,
    }


# ─── 综合专家判定 ──────────────────────────────────────────

def expert_full_analysis(image_bgr: np.ndarray, profile: str = "wood") -> dict[str, Any]:
    """
    一站式专家级对色分析.

    模拟对色老员工的完整工作流:
      1. 扫一眼所有板子 → 多板一致性
      2. 看色调方向 → 方向性诊断
      3. 看纹理 → 纹理一致性
      4. 给结论 → 人话总结
    """
    # Step 1: 多板一致性
    consistency = expert_multi_plank_consistency(image_bgr)
    planks = consistency.get("planks", [])
    n = consistency.get("plank_count", 0)

    # Step 2: 方向性诊断 (用第一块板为参考, 与其他对比)
    diagnoses = []
    if n >= 2:
        ref_lab = planks[0]["mean_lab"]
        for i in range(1, n):
            diag = _directional_diagnosis(ref_lab, planks[i]["mean_lab"], profile)
            diagnoses.append({"plank": i + 1, "vs_plank": 1, **diag})

    # Step 3: 纹理一致性
    texture = expert_texture_consistency(image_bgr, planks)

    # Step 4: 综合判定
    worst_de = consistency.get("worst_delta_e", 0)
    avg_de = consistency.get("avg_delta_e", 0)
    texture_ok = texture.get("texture_consistent", True)

    # 阈值 (模拟老员工经验)
    thresholds = {
        "wood": {"pass": 1.8, "marginal": 3.5},
        "stone": {"pass": 2.2, "marginal": 4.0},
        "solid": {"pass": 1.0, "marginal": 2.0},
        "metallic": {"pass": 1.5, "marginal": 3.0},
    }
    th = thresholds.get(profile, thresholds["wood"])

    if worst_de <= th["pass"] and texture_ok:
        verdict = "PASS"
        confidence = min(0.98, 0.85 + (th["pass"] - worst_de) / th["pass"] * 0.13)
    elif worst_de <= th["marginal"]:
        verdict = "MARGINAL"
        confidence = 0.65 + (th["marginal"] - worst_de) / th["marginal"] * 0.15
    else:
        verdict = "FAIL"
        confidence = max(0.3, 0.6 - (worst_de - th["marginal"]) / 5)

    if not texture_ok and verdict == "PASS":
        verdict = "MARGINAL"
        confidence *= 0.85

    # 生成人话总结
    summary_parts = []
    summary_parts.append(f"检测到{n}块板材")

    if verdict == "PASS":
        summary_parts.append(f"整体色调一致, 最大色差ΔE={worst_de:.2f}")
        summary_parts.append("建议放行")
    elif verdict == "MARGINAL":
        summary_parts.append(f"色差在临界范围 (最大ΔE={worst_de:.2f})")
        if diagnoses:
            worst_diag = max(diagnoses, key=lambda d: d.get("dE", 0))
            summary_parts.append(f"{worst_diag['plank']}号板{worst_diag['detail']}")
        summary_parts.append("建议人工复核后决定")
    else:
        summary_parts.append(f"色差超标 (最大ΔE={worst_de:.2f})")
        if diagnoses:
            worst_diag = max(diagnoses, key=lambda d: d.get("dE", 0))
            summary_parts.append(f"主要问题: {worst_diag['plank']}号板{worst_diag['detail']}")
        summary_parts.append("建议退回调色")

    if not texture_ok:
        summary_parts.append(f"另: {texture['human_summary']}")

    return {
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "human_summary": ", ".join(summary_parts) + "。",
        "plank_count": n,
        "avg_delta_e": avg_de,
        "worst_delta_e": worst_de,
        "consistency": consistency,
        "diagnoses": diagnoses,
        "texture": texture,
        "profile_used": profile,
    }
