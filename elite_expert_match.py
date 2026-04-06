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

        # 宽高比 (板材通常是长条形 w:h > 1.5)
        rect_w = max(rect[1][0], rect[1][1])
        rect_h = min(rect[1][0], rect[1][1])
        aspect = rect_w / max(rect_h, 1)

        # 背景判断: 水泥地面 = 低色度+低纹理+非长条形
        is_background = (chroma < 5 and texture < 100) or (chroma < 3)
        # 非常小或非常方的区域更可能是背景碎片
        if ratio < 0.03 and aspect < 1.5:
            is_background = True

        planks.append({
            "aspect_ratio": round(aspect, 2),
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

    # 去重: 合并中心点距离过近的候选 (取面积较大的)
    merged = []
    for p in product_planks:
        is_dup = False
        for m in merged:
            dx = abs(p["center"][0] - m["center"][0])
            dy = abs(p["center"][1] - m["center"][1])
            if dx < w * 0.08 and dy < h * 0.08:
                is_dup = True
                break
        if not is_dup:
            merged.append(p)
    product_planks = merged

    # 限制最大板材数 (真实场景通常2-8块)
    product_planks = product_planks[:8]

    # 编号
    for idx, p in enumerate(product_planks):
        p["plank_id"] = idx + 1

    return product_planks


# ─── 创新算法1: 接缝线色差检测 (Edge Seam ΔE) ─────────────

def expert_seam_compare(image_bgr: np.ndarray,
                        planks: list[dict[str, Any]] | None = None,
                        sample_points: int = 20) -> dict[str, Any]:
    """
    沿板材接缝线取色对比 — 模拟老员工把两块板靠在一起看的方式.

    原理: 人眼对相邻区域色差最敏感 (同时对比效应).
    在两块板的交界处, 左右各取一条窄带(5px), 逐点计算ΔE.
    这比全板平均值更接近人眼实际感知.
    """
    h, w = image_bgr.shape[:2]
    if planks is None:
        planks = _detect_plank_regions(image_bgr)
    if len(planks) < 2:
        return {"seam_count": 0, "seams": [], "human_summary": "板数不足, 无接缝可对比"}

    lab = bgr_to_lab_float32(image_bgr)

    # 找所有相邻板对: 用中心距离判断, 最近边距<25%图像尺寸
    seams = []

    for idx in range(len(planks)):
      for jdx in range(idx + 1, len(planks)):
        p1 = planks[idx]
        p2 = planks[jdx]

        box1 = p1["box"]
        box2 = p2["box"]

        # 计算两板最近边距
        y1_min, y1_max = int(box1[:, 1].min()), int(box1[:, 1].max())
        y2_min, y2_max = int(box2[:, 1].min()), int(box2[:, 1].max())
        x1_min, x1_max = int(box1[:, 0].min()), int(box1[:, 0].max())
        x2_min, x2_max = int(box2[:, 0].min()), int(box2[:, 0].max())

        # Y方向间距 (负=重叠)
        y_gap = max(y2_min - y1_max, y1_min - y2_max)
        # X方向间距
        x_gap = max(x2_min - x1_max, x1_min - x2_max)

        # 至少一个方向是近邻
        is_y_adjacent = -h * 0.15 < y_gap < h * 0.25
        is_x_adjacent = -w * 0.15 < x_gap < w * 0.25
        # 另一方向要有重叠
        y_overlap = y1_max > y2_min and y2_max > y1_min
        x_overlap = x1_max > x2_min and x2_max > x1_min

        if is_x_adjacent and y_overlap:
            # 水平相邻: 取左板右缘 vs 右板左缘
            x_seam = (min(x1_max, x2_max) + max(x1_min, x2_min)) // 2
            y_start = max(y1_min, y2_min, 0)
            y_end = min(y1_max, y2_max, h)
            if y_end - y_start < 20:
                continue
            strip_width = 5
            left_strip = lab[y_start:y_end, max(0, x_seam - strip_width):x_seam]
            right_strip = lab[y_start:y_end, x_seam:min(w, x_seam + strip_width)]
        elif is_y_adjacent and x_overlap:
            # 垂直相邻
            y_seam = (min(y1_max, y2_max) + max(y1_min, y2_min)) // 2
            x_start = max(x1_min, x2_min, 0)
            x_end = min(x1_max, x2_max, w)
            if x_end - x_start < 20:
                continue
            strip_width = 5
            left_strip = lab[max(0, y_seam - strip_width):y_seam, x_start:x_end]
            right_strip = lab[y_seam:min(h, y_seam + strip_width), x_start:x_end]
        else:
            continue

        if left_strip.size < 30 or right_strip.size < 30:
            continue

        # 沿接缝均匀采样N个点
        seam_length = max(left_strip.shape[0], left_strip.shape[1])
        step = max(1, seam_length // sample_points)
        point_des = []

        for s in range(0, seam_length, step):
            if left_strip.shape[0] > left_strip.shape[1]:
                # 垂直方向采样
                if s >= left_strip.shape[0] or s >= right_strip.shape[0]:
                    break
                l1 = left_strip[s].mean(axis=0)
                l2 = right_strip[s].mean(axis=0) if s < right_strip.shape[0] else right_strip[-1].mean(axis=0)
            else:
                # 水平方向采样
                if s >= left_strip.shape[1] or s >= right_strip.shape[1]:
                    break
                l1 = left_strip[:, s].mean(axis=0)
                l2 = right_strip[:, s].mean(axis=0) if s < right_strip.shape[1] else right_strip[:, -1].mean(axis=0)

            de = ciede2000_scalar(float(l1[0]), float(l1[1]), float(l1[2]),
                                  float(l2[0]), float(l2[1]), float(l2[2]))
            point_des.append(de["total"])

        if not point_des:
            continue

        avg_seam_de = float(np.mean(point_des))
        max_seam_de = float(np.max(point_des))
        p50_seam_de = float(np.median(point_des))

        diag = _directional_diagnosis(
            (float(left_strip.reshape(-1, 3)[:, 0].mean()),
             float(left_strip.reshape(-1, 3)[:, 1].mean()),
             float(left_strip.reshape(-1, 3)[:, 2].mean())),
            (float(right_strip.reshape(-1, 3)[:, 0].mean()),
             float(right_strip.reshape(-1, 3)[:, 1].mean()),
             float(right_strip.reshape(-1, 3)[:, 2].mean())),
            "wood"
        )

        seams.append({
            "plank_a": p1.get("plank_id", idx + 1),
            "plank_b": p2.get("plank_id", idx + 2),
            "sample_count": len(point_des),
            "avg_seam_dE": round(avg_seam_de, 3),
            "max_seam_dE": round(max_seam_de, 3),
            "median_seam_dE": round(p50_seam_de, 3),
            "diagnosis": diag["short"],
            "point_dEs": [round(d, 2) for d in point_des[:10]],
        })

    worst_seam = max(seams, key=lambda s: s["avg_seam_dE"]) if seams else None

    summary = f"检测到{len(seams)}条接缝"
    if worst_seam:
        summary += f", 最大接缝色差ΔE={worst_seam['avg_seam_dE']:.2f} ({worst_seam['plank_a']}号↔{worst_seam['plank_b']}号: {worst_seam['diagnosis']})"
    return {
        "seam_count": len(seams),
        "seams": seams,
        "worst_seam": worst_seam,
        "human_summary": summary,
    }


# ─── 创新算法2: 视觉显著性加权色差 (Perceptual Saliency ΔE) ───

def _perceptual_weighted_de(lab1_region: np.ndarray, lab2_region: np.ndarray,
                             mask1: np.ndarray | None = None, mask2: np.ndarray | None = None) -> dict[str, float]:
    """
    视觉显著性加权色差 — 人眼对不同区域的关注度不同.

    原理:
      1. 中心权重高 (人眼先看中间)
      2. 平坦区域权重高 (纹理区域色差被掩蔽)
      3. 高亮度区域权重高 (暗区色差不易察觉)

    这比简单平均ΔE更接近人眼的实际感受.
    """
    h1, w1 = lab1_region.shape[:2]
    h2, w2 = lab2_region.shape[:2]

    # 统一尺寸
    th = min(h1, h2, 200)
    tw = min(w1, w2, 200)
    r1 = cv2.resize(lab1_region, (tw, th))
    r2 = cv2.resize(lab2_region, (tw, th))

    # 1. 中心权重 (高斯分布, 中心=1.0, 边缘=0.3)
    cy, cx = th // 2, tw // 2
    yy, xx = np.mgrid[:th, :tw]
    center_w = 0.3 + 0.7 * np.exp(-((yy - cy) ** 2 / (th * 0.8) ** 2 + (xx - cx) ** 2 / (tw * 0.8) ** 2))

    # 2. 纹理掩蔽权重 (平坦区域→高权重, 纹理区域→低权重)
    gray1 = r1[:, :, 0]  # L channel
    lap = cv2.Laplacian(gray1.astype(np.float32), cv2.CV_32F)
    texture_energy = np.abs(lap)
    max_tex = float(texture_energy.max()) + 1e-6
    texture_w = 1.0 - 0.5 * (texture_energy / max_tex)  # 纹理高→权重低

    # 3. 亮度权重 (暗区色差不易感知)
    brightness_w = np.clip(r1[:, :, 0] / 60.0, 0.3, 1.0)

    # 综合权重
    weights = center_w * texture_w * brightness_w
    weights /= weights.sum() + 1e-10

    # 逐像素ΔE (简化: 用欧氏距离近似, 真实CIEDE2000太慢)
    diff = r1.astype(np.float64) - r2.astype(np.float64)
    pixel_de = np.sqrt(diff[:, :, 0] ** 2 + diff[:, :, 1] ** 2 + diff[:, :, 2] ** 2)

    # 加权ΔE
    weighted_de = float((pixel_de * weights).sum())
    unweighted_de = float(pixel_de.mean())

    # 用全局LAB均值算精确CIEDE2000
    m1 = r1.reshape(-1, 3).mean(axis=0)
    m2 = r2.reshape(-1, 3).mean(axis=0)
    precise_de = ciede2000_scalar(float(m1[0]), float(m1[1]), float(m1[2]),
                                   float(m2[0]), float(m2[1]), float(m2[2]))

    return {
        "perceptual_dE": round(weighted_de, 3),
        "simple_dE": round(unweighted_de, 3),
        "ciede2000": round(precise_de["total"], 3),
        "perceptual_vs_simple_ratio": round(weighted_de / max(unweighted_de, 0.01), 3),
        "note": "perceptual_dE更接近人眼感受: 中心区域+平坦区域+高亮区域权重更高",
    }


# ─── 创新算法3: 45°角色光泽差异检测 ──────────────────────────

def expert_gloss_variation(image_bgr: np.ndarray,
                           planks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    检测板材间的光泽差异 — 模拟老员工从侧面看板子的习惯.

    原理:
      高光泽材料在不同角度颜色变化更大.
      通过分析每块板的高光分布(specular highlights)推断光泽度.
      光泽不一致 = 即使颜色一样, 到客户手里也会看起来不同.
    """
    h, w = image_bgr.shape[:2]
    if planks is None:
        planks = _detect_plank_regions(image_bgr)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    gloss_scores = []
    for p in planks:
        box = p["box"]
        x0, y0 = max(0, box[:, 0].min()), max(0, box[:, 1].min())
        x1, y1 = min(w, box[:, 0].max()), min(h, box[:, 1].max())
        if x1 - x0 < 20 or y1 - y0 < 20:
            gloss_scores.append({"plank_id": p.get("plank_id", 0), "gloss": 0, "valid": False})
            continue

        roi_gray = gray[y0:y1, x0:x1]
        roi_v = hsv[y0:y1, x0:x1, 2]  # Value channel

        # 光泽指标1: 高光像素比例 (V>230)
        specular_ratio = float(np.mean(roi_v > 230))

        # 光泽指标2: 亮度标准差 (高光泽=高方差, 因为有specular反射)
        brightness_std = float(roi_gray.astype(np.float32).std())

        # 光泽指标3: 梯度峰值 (高光泽面有锐利的亮度跳变)
        grad = cv2.Sobel(roi_gray, cv2.CV_64F, 1, 0, ksize=3)
        grad_peak = float(np.percentile(np.abs(grad), 95))

        # 综合光泽分数 (0-100)
        gloss = min(100, (specular_ratio * 200 + brightness_std * 0.5 + grad_peak * 0.1))

        gloss_scores.append({
            "plank_id": p.get("plank_id", 0),
            "gloss": round(gloss, 1),
            "specular_ratio": round(specular_ratio, 4),
            "brightness_std": round(brightness_std, 1),
            "valid": True,
        })

    valid = [g for g in gloss_scores if g["valid"]]
    if len(valid) < 2:
        return {"gloss_consistent": True, "variation": 0, "scores": gloss_scores,
                "human_summary": "板数不足, 无法对比光泽"}

    values = [g["gloss"] for g in valid]
    mean_gloss = float(np.mean(values))
    max_diff = float(max(values) - min(values))
    cv_gloss = float(np.std(values) / max(mean_gloss, 0.1))

    issues = []
    for g in valid:
        if abs(g["gloss"] - mean_gloss) > max(mean_gloss * 0.3, 5):
            label = "偏亮(高光泽)" if g["gloss"] > mean_gloss else "偏哑(低光泽)"
            issues.append({"plank": g["plank_id"], "issue": label,
                           "diff": round(g["gloss"] - mean_gloss, 1)})

    consistent = max_diff < max(mean_gloss * 0.4, 8)
    summary = f"平均光泽度={mean_gloss:.0f}, 最大差异={max_diff:.0f}"
    if not consistent:
        summary += f", ⚠光泽不一致"
        if issues:
            summary += f": {issues[0]['plank']}号板{issues[0]['issue']}"

    return {
        "gloss_consistent": consistent,
        "mean_gloss": round(mean_gloss, 1),
        "max_diff": round(max_diff, 1),
        "cv": round(cv_gloss, 3),
        "scores": gloss_scores,
        "issues": issues,
        "human_summary": summary,
    }


# ─── 多板一致性检测 ──────────────────────────────────────

def _cluster_same_product(planks: list[dict[str, Any]], max_de: float = 8.0) -> list[dict[str, Any]]:
    """聚类同色系板材 — 只保留最大同色系群组(同一产品).

    使用完全链接聚类(complete-linkage): 组内所有板两两ΔE都<max_de.
    比单链更严格, 避免通过中间板间接连通不同色号.
    """
    if len(planks) <= 2:
        return planks
    n = len(planks)
    # 计算距离矩阵
    de_mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            li, ai, bi = planks[i]["mean_lab"]
            lj, aj, bj = planks[j]["mean_lab"]
            de = ciede2000_scalar(li, ai, bi, lj, aj, bj)["total"]
            de_mat[i][j] = de
            de_mat[j][i] = de

    # 贪心完全链接: 从面积最大的板开始, 逐个添加与组内所有板ΔE<max_de的板
    sorted_idx = sorted(range(n), key=lambda i: planks[i]["area_ratio"], reverse=True)
    best_group = [sorted_idx[0]]
    for idx in sorted_idx[1:]:
        # 检查与组内所有成员的ΔE
        all_close = all(de_mat[idx][g] < max_de for g in best_group)
        if all_close:
            best_group.append(idx)

    # 如果组太小, 放宽重试
    if len(best_group) < 2 and n >= 2:
        best_group = [sorted_idx[0]]
        for idx in sorted_idx[1:]:
            all_close = all(de_mat[idx][g] < max_de * 1.5 for g in best_group)
            if all_close:
                best_group.append(idx)

    return [planks[i] for i in sorted(best_group)]


def expert_multi_plank_consistency(image_bgr: np.ndarray) -> dict[str, Any]:
    """检测所有板材的一致性. 模拟老员工一眼扫过所有板子."""
    all_planks = _detect_plank_regions(image_bgr)
    # 聚类同色系板材 — 过滤掉不同产品/背景碎片
    planks = _cluster_same_product(all_planks, max_de=12.0)
    n = len(planks)
    # 重新编号
    for idx, p in enumerate(planks):
        p["plank_id"] = idx + 1

    if n < 2:
        return {
            "plank_count": n,
            "total_detected": len(all_planks),
            "consistency": "insufficient_planks",
            "human_summary": f"检测到{len(all_planks)}个区域, 同色系{n}块, 无法对比",
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

    # Step 4: 接缝线色差 (创新: 沿接缝逐点取色)
    seam = expert_seam_compare(image_bgr, planks)

    # Step 5: 光泽一致性 (创新: 检测高光分布)
    gloss = expert_gloss_variation(image_bgr, planks)

    # Step 6: 综合判定 — 融合全部5个维度
    worst_de = consistency.get("worst_delta_e", 0)
    avg_de = consistency.get("avg_delta_e", 0)
    texture_ok = texture.get("texture_consistent", True)
    gloss_ok = gloss.get("gloss_consistent", True)
    worst_seam_de = seam.get("worst_seam", {}).get("avg_seam_dE", 0) if seam.get("worst_seam") else 0

    # 阈值 (模拟老员工经验)
    thresholds = {
        "wood": {"pass": 1.8, "marginal": 3.5},
        "stone": {"pass": 2.2, "marginal": 4.0},
        "solid": {"pass": 1.0, "marginal": 2.0},
        "metallic": {"pass": 1.5, "marginal": 3.0},
    }
    th = thresholds.get(profile, thresholds["wood"])

    # 使用接缝ΔE和全局ΔE中较高的作为判定依据 (更接近人眼)
    effective_de = max(worst_de, worst_seam_de)

    if effective_de <= th["pass"] and texture_ok and gloss_ok:
        verdict = "PASS"
        confidence = min(0.98, 0.85 + (th["pass"] - effective_de) / th["pass"] * 0.13)
    elif effective_de <= th["marginal"]:
        verdict = "MARGINAL"
        confidence = 0.65 + (th["marginal"] - effective_de) / th["marginal"] * 0.15
    else:
        verdict = "FAIL"
        confidence = max(0.3, 0.6 - (effective_de - th["marginal"]) / 5)

    if not texture_ok and verdict == "PASS":
        verdict = "MARGINAL"
        confidence *= 0.85
    if not gloss_ok and verdict == "PASS":
        verdict = "MARGINAL"
        confidence *= 0.90

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
        summary_parts.append(f"纹理: {texture['human_summary']}")
    if not gloss_ok:
        summary_parts.append(f"光泽: {gloss['human_summary']}")
    if seam.get("worst_seam"):
        ws = seam["worst_seam"]
        summary_parts.append(f"接缝色差ΔE={ws['avg_seam_dE']:.2f}")

    return {
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "human_summary": ", ".join(summary_parts) + "。",
        "plank_count": n,
        "effective_delta_e": round(effective_de, 3),
        "avg_delta_e": avg_de,
        "worst_delta_e": worst_de,
        "consistency": consistency,
        "diagnoses": diagnoses,
        "seam_analysis": seam,
        "texture": texture,
        "gloss": gloss,
        "profile_used": profile,
    }
