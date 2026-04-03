"""
SENIA 白色标签定位器
===================
利用标样上总有白色小标签这一物理特征,
精确定位标样区域. 比任何颜色算法都可靠.
"""

from __future__ import annotations
from typing import Any
import cv2
import numpy as np


def find_sample_by_white_label(
    image_bgr: np.ndarray,
    product_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    通过检测白色标签定位标样.

    逻辑:
      1. 检测白色小矩形 (标签)
      2. 标签在产品前景内 → 在标样上
      3. 从标签位置向外扩展 → 找到标样的完整区域
      4. 返回标样区域的 quad 坐标

    返回: {found: bool, sample_rect: (x,y,w,h), label_pos: (x,y)}
    """
    h, w = image_bgr.shape[:2]
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # Step 1: 检测白色区域
    white = ((hsv[..., 2] > 190) & (hsv[..., 1] < 50)).astype(np.uint8)
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    white = cv2.morphologyEx(white, cv2.MORPH_OPEN, np.ones((6, 6), np.uint8))

    # 只保留产品前景内的白色
    if product_mask is not None:
        white = white & product_mask

    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 过滤: 面积 200-20000, 宽高比 < 5
    labels = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 200 or area > 20000:
            continue
        x, y, rw, rh = cv2.boundingRect(cnt)
        aspect = max(rw, rh) / (min(rw, rh) + 1)
        if aspect > 5:
            continue
        labels.append({"x": x, "y": y, "w": rw, "h": rh, "area": area,
                        "cx": x + rw // 2, "cy": y + rh // 2})

    if not labels:
        return {"found": False, "reason": "no_white_labels"}

    # Step 2: 从标签位置推断标样区域
    # 标样特征: 标签通常在标样的角上或边上
    # 标样是一个长条, 宽 ~100-300px, 长 ~300-1200px
    # 从标签位置沿上下左右找颜色一致的长条形区域

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    best_sample = None
    best_score = -1

    for label in labels:
        lx, ly = label["cx"], label["cy"]

        # 从标签位置向四个方向扫描, 找颜色一致的区域
        # 策略: 标签附近的像素颜色应该和标样颜色一致
        # 采样标签周围 30px 的颜色作为标样参考色
        py0 = max(0, ly - 40)
        py1 = min(h, ly + 40)
        px0 = max(0, lx - 40)
        px1 = min(w, lx + 40)

        ref_region = gray[py0:py1, px0:px1]
        if ref_region.size < 100:
            continue
        ref_val = float(np.median(ref_region))

        # 向各方向扩展: 找 brightness 接近 ref_val 的连续区域
        # 用 floodFill 的简化版: 行/列扫描
        tolerance = 15  # 灰度容差

        # 向上扫描
        top = ly
        for y in range(ly, max(0, ly - 800), -1):
            row = gray[y, max(0, lx - 50):min(w, lx + 50)]
            if abs(float(np.median(row)) - ref_val) > tolerance:
                top = y + 1
                break
            top = y

        # 向下扫描
        bottom = ly
        for y in range(ly, min(h, ly + 800)):
            row = gray[y, max(0, lx - 50):min(w, lx + 50)]
            if abs(float(np.median(row)) - ref_val) > tolerance:
                bottom = y - 1
                break
            bottom = y

        # 向左扫描
        left = lx
        for x in range(lx, max(0, lx - 400), -1):
            col = gray[max(0, ly - 30):min(h, ly + 30), x]
            if abs(float(np.median(col)) - ref_val) > tolerance:
                left = x + 1
                break
            left = x

        # 向右扫描
        right = lx
        for x in range(lx, min(w, lx + 400)):
            col = gray[max(0, ly - 30):min(h, ly + 30), x]
            if abs(float(np.median(col)) - ref_val) > tolerance:
                right = x - 1
                break
            right = x

        sw = right - left
        sh = bottom - top
        area = sw * sh

        # 标样面积合理性: 不能太大 (标样通常 < 15% 图面积)
        image_area = h * w
        if area < image_area * 0.005 or area > image_area * 0.15:
            continue
        if sw < 30 or sh < 30:
            continue

        # 标样必须是长条形 (宽窄比 > 2)
        aspect = max(sw, sh) / (min(sw, sh) + 1)
        if aspect < 1.5:
            continue  # 太方了, 不像标样
        score = area * (1.5 if 2.5 < aspect < 6 else 0.8)

        if product_mask is not None:
            fg_ratio = product_mask[top:bottom, left:right].mean() if sh > 0 and sw > 0 else 0
            score *= fg_ratio

        if score > best_score:
            best_score = score
            best_sample = {
                "x": left, "y": top, "w": sw, "h": sh,
                "label_pos": (label["cx"], label["cy"]),
                "area": area,
                "aspect": round(aspect, 1),
            }

    if best_sample is None:
        return {"found": False, "reason": "no_valid_sample_region"}

    return {
        "found": True,
        "sample_rect": (best_sample["x"], best_sample["y"],
                        best_sample["w"], best_sample["h"]),
        "label_pos": best_sample["label_pos"],
        "area_ratio": round(best_sample["area"] / (h * w), 4),
        "aspect": best_sample["aspect"],
    }
