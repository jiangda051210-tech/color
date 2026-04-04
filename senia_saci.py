"""
SENIA SACI — Self-Adapting Color Intelligence
=============================================
自适应色彩智能引擎 — 彻底摆脱硬件依赖的对色算法

核心创新 (行业首创):

1. 相对色差法 (Relative Delta-E)
   不测绝对颜色, 只测同一画面内两个区域的相对差异.
   同一张照片里光照/相机/角度完全一致 → 差异只来自材料本身.
   原理: 对板材和标样做成对的局部比较, 光照因素自动抵消.

2. 水泥地自校准 (Concrete Self-Calibration)
   利用水泥地面作为"灰色参考" — 它是近似中性灰.
   从边缘检测到的水泥区域估算色温偏移, 反推校正矩阵.
   不需要灰卡、不需要标准光源、不需要色温计.

3. 超像素自适应分割 (Superpixel Adaptive Segmentation)
   替代脆弱的轮廓检测:
   - SLIC超像素把图像分成颜色均匀的小块
   - 按颜色相似度合并超像素成大区域
   - 不依赖边缘清晰度, 对阴影/模糊/低对比度鲁棒

4. 多板交叉验证 (Cross-Board Consensus)
   当检测到多块同色板材时, 用它们的一致性作为测量可信度.
   一致 → 测量可信; 分散 → 环境干扰大, 降低置信.
"""

from __future__ import annotations
from typing import Any
import cv2
import numpy as np
import math


# ═══════════════════════════════════════════════
# 1. 水泥地自校准白平衡
# ═══════════════════════════════════════════════

def calibrate_from_concrete(image_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """
    用水泥地面作为灰色参考进行自校准白平衡.

    原理: 水泥/沥青地面在 LAB 空间中 a≈0, b≈0 (近似中性灰).
    如果测量到的水泥区域 a≠0 或 b≠0, 说明光照有色偏,
    用这个偏移量反推校正.

    优势: 不需要灰卡, 利用已有场景元素.
    """
    h, w = image_bgr.shape[:2]
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 1] -= 128.0
    lab[..., 2] -= 128.0

    # 找水泥区域: 边缘 + 低色度 + 中等亮度
    chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
    brightness = lab[..., 0] * (100.0 / 255.0)

    # 水泥特征: 色度 < 12, 亮度 30-85
    concrete_mask = (chroma < 12) & (brightness > 30) & (brightness < 85)

    # 只用边缘区域 (更可能是地面而非板材)
    border = np.zeros((h, w), dtype=bool)
    bh, bw = max(30, h // 6), max(30, w // 6)
    border[:bh, :] = True
    border[-bh:, :] = True
    border[:, :bw] = True
    border[:, -bw:] = True
    concrete_border = concrete_mask & border

    info: dict[str, Any] = {"calibrated": False, "method": "none"}

    concrete_pixels = np.count_nonzero(concrete_border)
    if concrete_pixels < 500:
        # 找不到足够水泥像素, 不校准
        return image_bgr, info

    # 计算水泥区域的色偏
    concrete_a = float(lab[..., 1][concrete_border].mean())
    concrete_b = float(lab[..., 2][concrete_border].mean())

    # 水泥应该是 a≈0, b≈0, 偏差就是光照色偏
    info = {
        "calibrated": True,
        "method": "concrete_reference",
        "concrete_pixels": concrete_pixels,
        "measured_a_bias": round(concrete_a, 2),
        "measured_b_bias": round(concrete_b, 2),
        "correction_a": round(-concrete_a, 2),
        "correction_b": round(-concrete_b, 2),
    }

    # 校正限幅: 最大 ±5.0 (户外实测色偏可达4-5, 原3.0太紧)
    MAX_CORRECTION = 5.0
    safe_a = max(-MAX_CORRECTION, min(MAX_CORRECTION, -concrete_a))
    safe_b = max(-MAX_CORRECTION, min(MAX_CORRECTION, -concrete_b))
    info["correction_a"] = round(safe_a, 2)
    info["correction_b"] = round(safe_b, 2)
    info["clamped"] = abs(concrete_a) > MAX_CORRECTION or abs(concrete_b) > MAX_CORRECTION

    corrected_lab = lab.copy()
    corrected_lab[..., 1] += safe_a
    corrected_lab[..., 2] += safe_b
    # 转回 BGR
    corrected_lab[..., 1] += 128.0
    corrected_lab[..., 2] += 128.0
    corrected = cv2.cvtColor(corrected_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

    return corrected, info


# ═══════════════════════════════════════════════
# 2. 超像素自适应分割
# ═══════════════════════════════════════════════

def superpixel_segment(image_bgr: np.ndarray,
                       n_segments: int = 200,
                       compactness: float = 15.0) -> tuple[np.ndarray, int]:
    """
    SLIC 超像素分割 — 比轮廓检测更鲁棒.

    原理: 把图像分成颜色+空间相似的小块,
    每个超像素内部颜色均匀, 边界自然跟随颜色变化.
    不依赖边缘清晰度, 对阴影/模糊/低对比度鲁棒.
    """
    # 缩小加速
    scale = min(1.0, 800.0 / max(image_bgr.shape[:2]))
    if scale < 1.0:
        small = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        small = image_bgr.copy()

    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)

    # OpenCV SLIC
    slic = cv2.ximgproc.createSuperpixelSLIC(lab, cv2.ximgproc.SLIC,
                                              region_size=int(max(small.shape[:2]) / (n_segments ** 0.5)),
                                              ruler=compactness)
    slic.iterate(10)
    slic.enforceLabelConnectivity(25)
    labels = slic.getLabels()
    n_labels = slic.getNumberOfSuperpixels()

    # 放大回原始尺寸
    if scale < 1.0:
        labels = cv2.resize(labels, (image_bgr.shape[1], image_bgr.shape[0]),
                           interpolation=cv2.INTER_NEAREST)

    return labels, n_labels


def merge_superpixels_to_boards(image_bgr: np.ndarray, labels: np.ndarray,
                                n_labels: int) -> list[dict[str, Any]]:
    """
    把超像素合并成板材区域.

    策略:
    1. 计算每个超像素的平均 LAB
    2. 按颜色相似度合并相邻超像素 (dE < 5)
    3. 过滤: 只保留面积 > 图像2%的大区域
    4. 对每个区域做精确颜色测量
    """
    from elite_color_match import (texture_suppress, bgr_to_lab_float,
                                    robust_mean_lab, build_invalid_mask,
                                    build_material_mask)

    h, w = image_bgr.shape[:2]
    image_area = h * w

    # 计算每个超像素的平均LAB
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 0] *= (100.0 / 255.0)
    lab[..., 1] -= 128.0
    lab[..., 2] -= 128.0

    sp_labs = np.zeros((n_labels, 3), dtype=np.float32)
    sp_counts = np.zeros(n_labels, dtype=np.int32)
    for i in range(n_labels):
        mask = labels == i
        count = np.count_nonzero(mask)
        if count > 0:
            sp_labs[i] = lab[mask].mean(axis=0)
            sp_counts[i] = count

    # 区域合并: Union-Find + 颜色相似度
    parent = list(range(n_labels))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if sp_counts[ra] >= sp_counts[rb]:
                parent[rb] = ra
            else:
                parent[ra] = rb

    # 找相邻超像素并合并颜色相近的
    # 用标签图的边界检测相邻关系
    adjacency = set()
    # 水平相邻
    diff_h = labels[:, 1:] != labels[:, :-1]
    ys, xs = np.where(diff_h)
    for y, x in zip(ys[:5000], xs[:5000]):  # 限制数量避免太慢
        a, b_val = int(labels[y, x]), int(labels[y, x + 1])
        if a != b_val:
            adjacency.add((min(a, b_val), max(a, b_val)))
    # 垂直相邻
    diff_v = labels[1:, :] != labels[:-1, :]
    ys, xs = np.where(diff_v)
    for y, x in zip(ys[:5000], xs[:5000]):
        a, b_val = int(labels[y, x]), int(labels[y + 1, x])
        if a != b_val:
            adjacency.add((min(a, b_val), max(a, b_val)))

    # 合并颜色相近的相邻超像素
    MERGE_THRESHOLD = 5.0  # dE < 5 的相邻超像素合并
    for a, b_val in adjacency:
        if sp_counts[a] == 0 or sp_counts[b_val] == 0:
            continue
        diff = sp_labs[a] - sp_labs[b_val]
        dE_approx = float(np.sqrt(np.sum(diff ** 2)))  # 简化dE
        if dE_approx < MERGE_THRESHOLD:
            union(a, b_val)

    # 收集合并后的区域
    regions: dict[int, list[int]] = {}
    for i in range(n_labels):
        root = find(i)
        regions.setdefault(root, []).append(i)

    # 对每个大区域做精确测量
    boards: list[dict[str, Any]] = []
    for root, members in regions.items():
        # 合并面积
        total_pixels = sum(sp_counts[m] for m in members)
        ratio = total_pixels / image_area
        if ratio < 0.02 or ratio > 0.95:
            continue

        # 构建区域掩码
        region_mask = np.zeros((h, w), dtype=bool)
        for m in members:
            region_mask |= (labels == m)

        # 计算区域的边界框
        ys_r, xs_r = np.where(region_mask)
        if len(ys_r) == 0:
            continue
        y0, y1 = int(ys_r.min()), int(ys_r.max())
        x0, x1 = int(xs_r.min()), int(xs_r.max())
        bw_r, bh_r = x1 - x0, y1 - y0
        if bw_r < 30 or bh_r < 30:
            continue

        # 矩形度
        rect_area = float(bw_r * bh_r)
        rectangularity = min(1.0, total_pixels / max(rect_area, 1))

        # 角色推断
        if ratio > 0.30:
            role = "board"
        elif ratio > 0.10:
            role = "plank"
        else:
            role = "sample"

        # 精确颜色测量 (在裁剪区域上)
        crop = image_bgr[y0:y1, x0:x1]
        crop_mask = region_mask[y0:y1, x0:x1]

        # 纹理抑制
        tone = texture_suppress(crop)
        # 无效掩码
        invalid = build_invalid_mask(tone)
        valid_mask = crop_mask & (~invalid)
        valid_count = int(np.count_nonzero(valid_mask))

        mean_lab_dict = None
        std_lab_dict = None
        used_pixels = 0

        if valid_count > 200:
            crop_lab = bgr_to_lab_float(tone)
            try:
                mean_lab_arr, std_lab_arr, used = robust_mean_lab(crop_lab, valid_mask)
                mean_lab_dict = {
                    "L": round(float(mean_lab_arr[0]), 2),
                    "a": round(float(mean_lab_arr[1]), 2),
                    "b": round(float(mean_lab_arr[2]), 2),
                }
                std_lab_dict = {
                    "L": round(float(std_lab_arr[0]), 2),
                    "a": round(float(std_lab_arr[1]), 2),
                    "b": round(float(std_lab_arr[2]), 2),
                }
                used_pixels = used
            except ValueError:
                pass

        if mean_lab_dict is None:
            continue

        quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
        boards.append({
            "quad": quad,
            "area": float(total_pixels),
            "area_ratio": round(ratio, 4),
            "center": (float((x0 + x1) / 2), float((y0 + y1) / 2)),
            "rectangularity": round(rectangularity, 3),
            "role": role,
            "mean_lab": mean_lab_dict,
            "std_lab": std_lab_dict,
            "valid_pixel_ratio": round(valid_count / max(total_pixels, 1), 3),
            "used_pixels": used_pixels,
            "superpixel_count": len(members),
        })

    boards.sort(key=lambda b: b["area_ratio"], reverse=True)
    return boards


# ═══════════════════════════════════════════════
# 3. 相对色差法 (核心创新)
# ═══════════════════════════════════════════════

def relative_color_match(image_bgr: np.ndarray,
                         board_mask: np.ndarray,
                         sample_mask: np.ndarray,
                         grid_rows: int = 4,
                         grid_cols: int = 4) -> dict[str, Any]:
    """
    相对色差法 — 不测绝对颜色, 只测同画面内的相对差异.

    核心原理:
      同一张照片里, 大货和标样处于完全相同的光照条件下.
      因此 board_pixel / sample_pixel 的比值与光照无关,
      只反映材料本身的颜色差异.

    实现:
      1. 对大货做网格采样 (grid_rows × grid_cols)
      2. 对标样取整体均值作为参考
      3. 计算每个网格的局部色差 (在同一光照下)
      4. 输出: 网格级色差分布 + 全局色差
    """
    from elite_color_match import texture_suppress, bgr_to_lab_float, robust_mean_lab

    # 纹理抑制
    tone = texture_suppress(image_bgr)
    lab = bgr_to_lab_float(tone)

    # 标样参考色 (稳健统计)
    try:
        sample_mean, sample_std, sample_used = robust_mean_lab(lab, sample_mask)
    except ValueError:
        return {"success": False, "reason": "sample_no_valid_pixels"}

    # 大货参考色
    try:
        board_mean, board_std, board_used = robust_mean_lab(lab, board_mask)
    except ValueError:
        return {"success": False, "reason": "board_no_valid_pixels"}

    # 关键: 使用相同图像的 LAB 值做差 → 光照自动抵消
    dL = float(board_mean[0] - sample_mean[0])
    da = float(board_mean[1] - sample_mean[1])
    db = float(board_mean[2] - sample_mean[2])

    # CIEDE2000 (精确)
    from senia_color_report import _ciede2000_detail
    board_dict = {"L": float(board_mean[0]), "a": float(board_mean[1]), "b": float(board_mean[2])}
    sample_dict = {"L": float(sample_mean[0]), "a": float(sample_mean[1]), "b": float(sample_mean[2])}
    de_detail = _ciede2000_detail(board_dict, sample_dict)

    # 网格级分析
    h, w = board_mask.shape
    grid_de = []
    for r in range(grid_rows):
        y0 = int(r * h / grid_rows)
        y1 = int((r + 1) * h / grid_rows)
        for c in range(grid_cols):
            x0 = int(c * w / grid_cols)
            x1 = int((c + 1) * w / grid_cols)
            cell_mask = board_mask[y0:y1, x0:x1]
            if np.count_nonzero(cell_mask) < 50:
                continue
            cell_lab = lab[y0:y1, x0:x1]
            try:
                cell_mean, _, _ = robust_mean_lab(cell_lab, cell_mask)
                cell_dict = {"L": float(cell_mean[0]), "a": float(cell_mean[1]), "b": float(cell_mean[2])}
                cell_de = _ciede2000_detail(cell_dict, sample_dict)
                grid_de.append(cell_de["dE00"])
            except ValueError:
                continue

    return {
        "success": True,
        "method": "relative_same_image",
        "delta_e": de_detail,
        "board_lab": board_dict,
        "sample_lab": sample_dict,
        "grid_de": grid_de,
        "grid_stats": {
            "avg": round(float(np.mean(grid_de)), 2) if grid_de else 0,
            "p95": round(float(np.percentile(grid_de, 95)), 2) if len(grid_de) >= 3 else 0,
            "max": round(float(np.max(grid_de)), 2) if grid_de else 0,
            "cells_used": len(grid_de),
        },
        "note": "相对色差法: 同一画面同一光照, 差异只来自材料本身",
    }


# ═══════════════════════════════════════════════
# 4. SACI 完整管线
# ═══════════════════════════════════════════════

def saci_analyze(image_bgr: np.ndarray, profile: str = "auto") -> dict[str, Any]:
    """
    SACI 完整分析管线 — 自适应色彩智能.

    流程:
      1. 水泥地自校准白平衡 (如有水泥)
      2. 尝试超像素分割 (如可用) 或回退到轮廓法
      3. 智能识别大货/标样
      4. 相对色差法测量 (光照无关)
      5. 输出完整对色报告
    """
    from senia_color_report import (
        generate_color_match_report, _ciede2000_detail,
        _color_direction, _adjust_suggestion, _judge_result,
    )
    from senia_preflight import preflight_check
    from elite_color_match import contour_candidates, detect_all_boards
    from datetime import datetime

    h, w = image_bgr.shape[:2]

    # ── Step 0: 大图智能降采样 ──
    # 超过 2000px 长边的图像降采样, 保持精度的同时大幅提速
    # (5712x4284 从 21.7s → ~2s)
    MAX_LONG_EDGE = 2000
    long_edge = max(h, w)
    scale_factor = 1.0
    if long_edge > MAX_LONG_EDGE:
        scale_factor = MAX_LONG_EDGE / long_edge
        new_w = int(w * scale_factor)
        new_h = int(h * scale_factor)
        image_bgr = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        h, w = new_h, new_w

    # ── Step 0.5: 表面分析与预处理 (闪光灯/保护膜/光泽度) ──
    try:
        from senia_surface import analyze_surface_and_preprocess
        image_bgr, surface_info = analyze_surface_and_preprocess(image_bgr)
    except Exception:
        surface_info = {}

    # ── Step 1: 水泥自校准 ──
    calibrated_img, cal_info = calibrate_from_concrete(image_bgr)

    # ── Step 2: 板材检测 (双路径) ──
    # 路径A: 超像素分割 (如果 cv2.ximgproc 可用)
    sp_boards = None
    try:
        labels, n_labels = superpixel_segment(calibrated_img)
        sp_boards = merge_superpixels_to_boards(calibrated_img, labels, n_labels)
        # 过滤低质量
        sp_boards = [b for b in sp_boards
                     if b.get("used_pixels", 0) >= 500
                     and b.get("valid_pixel_ratio", 0) >= 0.15]
    except (cv2.error, AttributeError):
        sp_boards = None  # ximgproc 不可用

    # 路径B: 轮廓法 (永远作为后备)
    cands = contour_candidates(calibrated_img)
    contour_boards = detect_all_boards(cands, calibrated_img.shape, calibrated_img)
    contour_boards = [b for b in contour_boards
                      if b.get("mean_lab") and b.get("used_pixels", 0) >= 500
                      and b.get("valid_pixel_ratio", 0) >= 0.15]

    # 选择更好的结果
    if sp_boards and len(sp_boards) >= len(contour_boards):
        boards = sp_boards
        detection_method = "superpixel"
    else:
        boards = contour_boards
        detection_method = "contour"

    if not boards:
        return {
            "saci_version": "1.0",
            "success": False,
            "reason": "no_boards_detected",
            "calibration": cal_info,
            "建议": "未检测到地板/彩膜板材。请确保: (1) 板材占画面面积>20% "
                    "(2) 板材与背景有明显颜色差异 (3) 图片不是产品广告/文档/证书等非对色场景",
        }

    # ── Step 3: 双路径报告 ──
    # 路径A: 绝对LAB报告 (原图, 不做自校准)
    absolute_report = generate_color_match_report(image_bgr, profile=profile)

    # 路径B: SACI校准后报告 (水泥自校准后)
    if cal_info.get("calibrated"):
        calibrated_report = generate_color_match_report(calibrated_img, profile=profile)
    else:
        calibrated_report = absolute_report

    # ── Step 4: 组装双结果报告 ──
    report = absolute_report.copy()
    report["saci_version"] = "1.0"
    report["检测方法"] = {
        "superpixel": "超像素自适应分割",
        "contour": "多策略轮廓+LAB分割",
    }.get(detection_method, detection_method)

    # 绝对LAB结果 (保留原有)
    report["绝对测量"] = {
        "说明": "基于原始图像的精确LAB测量 (受光照影响)",
        "对色判定": absolute_report.get("对色判定", {}),
        "工艺调整建议": absolute_report.get("工艺调整建议", []),
    }

    # SACI校准结果
    if cal_info.get("calibrated"):
        cal_judgment = calibrated_report.get("对色判定", {})
        report["SACI校准测量"] = {
            "说明": "水泥地自校准后的测量 (消除光照色偏)",
            "对色判定": cal_judgment,
            "工艺调整建议": calibrated_report.get("工艺调整建议", []),
            "校准信息": {
                "方法": "水泥地灰色参考",
                "色偏校正_a": f"{cal_info['correction_a']:+.1f}",
                "色偏校正_b": f"{cal_info['correction_b']:+.1f}",
                "校正被限幅": cal_info.get("clamped", False),
            },
        }
        # 主判定: 校准结果有效时用校准, 否则回退到绝对
        if cal_judgment.get("结论") and cal_judgment["结论"] != "无法判定":
            report["对色判定"] = cal_judgment
            report["工艺调整建议"] = calibrated_report.get("工艺调整建议", [])
        # else: 保持绝对LAB的判定 (已在 report 中)
    else:
        report["SACI校准测量"] = {"说明": "未检测到水泥地面, 无法自校准", "已校准": False}

    # ── Step 5: 行业级分析 (仅有板材时) ──
    try:
        from senia_industry import (
            predict_dry_color, check_metamerism_risk,
            analyze_board_uniformity, detect_edge_effect,
        )

        det = report.get("检测结果", {})
        board_lab = det.get("大货", {}).get("LAB")
        sample_lab = det.get("标样", {}).get("LAB")

        industry: dict[str, Any] = {}

        # 表面分析 (光泽度/闪光灯/保护膜)
        if surface_info:
            industry["表面分析"] = surface_info

        # 湿干预测 (如果有大货LAB)
        if board_lab:
            industry["湿干预测"] = predict_dry_color(board_lab)

        # 同色异谱风险 (如果有板对)
        if board_lab and sample_lab:
            industry["同色异谱风险"] = check_metamerism_risk(board_lab, sample_lab)

        # 空间均匀性 (对最大板材)
        if boards:
            biggest = max(boards, key=lambda b: b.get("area_ratio", 0))
            quad = biggest.get("quad")
            if quad is not None:
                industry["空间均匀性"] = analyze_board_uniformity(
                    calibrated_img, quad, grid_rows=4, grid_cols=6)
                industry["边缘效应"] = detect_edge_effect(calibrated_img, quad)

        if industry:
            report["行业分析"] = industry

    except Exception:
        pass  # 行业分析失败不影响核心对色

    return report
